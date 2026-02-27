import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional, Set

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from models import LogEntry, AnalysisResult
from agents import LogIngestor, SmartContextEngine, ErrorDetector, Analyzer, TaxonomyClassifier
from simulator import LogGenerator


def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


# Global state
class AppState:
    def __init__(self):
        self.log_generator: Optional[LogGenerator] = None
        self.log_ingestor: Optional[LogIngestor] = None
        self.context_engine: Optional[SmartContextEngine] = None
        self.error_detector: Optional[ErrorDetector] = None
        self.analyzer: Optional[Analyzer] = None
        self.classifier: Optional[TaxonomyClassifier] = None

        self.analysis_results: List[AnalysisResult] = []
        self.is_monitoring: bool = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._log_queue: Optional[asyncio.Queue] = None
        self._log_processor_task: Optional[asyncio.Task] = None

        # WebSocket connections for real-time dashboard
        self.websocket_connections: Set[WebSocket] = set()


app_state = AppState()


async def broadcast_to_websockets(message: dict):
    """Broadcast a message to all connected WebSocket clients."""
    disconnected = set()
    for ws in app_state.websocket_connections:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(ws)

    # Remove disconnected clients
    app_state.websocket_connections -= disconnected


def on_error_detected(log_entry: LogEntry, detection_result):
    """Callback when an error is detected."""
    print(
        f"[DETECTED] {detection_result.severity.upper()}: {log_entry.message}")


async def on_error_context(context_logs: List[LogEntry]):
    """Callback when error context is ready for analysis."""
    if not app_state.analyzer:
        return

    print(f"[ANALYZING] {len(context_logs)} log entries...")

    # Broadcast analysis start
    await broadcast_to_websockets({
        "type": "analysis_start",
        "data": {
            "context_size": len(context_logs),
        }
    })

    result = await app_state.analyzer.analyze(context_logs)
    if result:
        # Classify with SKILL.md taxonomy (OpenAI)
        if app_state.classifier:
            taxonomy = await app_state.classifier.classify(result)
            if taxonomy:
                result = result.model_copy(update={"taxonomy": taxonomy})

        app_state.analysis_results.append(result)
        # Keep only last 100 results
        if len(app_state.analysis_results) > 100:
            app_state.analysis_results = app_state.analysis_results[-100:]

        print(f"[RESULT] {result.severity.upper()}: {result.error_type}")
        if result.taxonomy:
            print(f"  [SKILL] {result.taxonomy.category} | event={result.taxonomy.event}")
        print(f"  Root cause: {result.root_cause[:80]}...")
        print(f"  Actions: {', '.join(result.corrective_actions[:2])}")

        # Build broadcast payload with taxonomy for dashboard
        data = {
            "id": result.id,
            "severity": result.severity,
            "error_type": result.error_type,
            "root_cause": result.root_cause,
            "corrective_actions": result.corrective_actions,
            "confidence": result.confidence,
            "affected_systems": result.affected_systems,
        }
        if result.taxonomy:
            data["taxonomy"] = result.taxonomy.model_dump()
            data["taxonomy_line"] = result.taxonomy_line()

        # Broadcast analysis result
        await broadcast_to_websockets({
            "type": "analysis_complete",
            "data": data,
        })


async def run_simulation():
    """Run the log generator in simulation mode."""
    if not app_state.log_generator:
        return

    try:
        async for _ in app_state.log_generator.generate():
            pass
    except asyncio.CancelledError:
        pass


async def run_simulation_continuous():
    """Run log generator continuously like a real robot."""
    if not app_state.log_generator:
        return

    try:
        async for _ in app_state.log_generator.generate():
            pass
    except asyncio.CancelledError:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print(f"Starting {settings.APP_NAME}...")

    # Initialize components
    app_state.analyzer = Analyzer()
    app_state.classifier = TaxonomyClassifier()

    app_state.error_detector = ErrorDetector(
        error_keywords=settings.ERROR_KEYWORDS,
        warning_keywords=settings.WARNING_KEYWORDS,
        on_error_detected=on_error_detected,
    )

    app_state.context_engine = SmartContextEngine(
        window_size=settings.CONTEXT_WINDOW_SIZE,
        timeout_sec=settings.CONTEXT_TIMEOUT_SEC,
        on_error_context=on_error_context,
    )

    # Use a queue to bridge sync watchdog thread with async event loop
    app_state._log_queue: asyncio.Queue = asyncio.Queue()

    app_state.log_ingestor = LogIngestor(
        log_file_path=settings.LOG_FILE_PATH,
        on_log_entry=lambda entry: app_state._log_queue.put_nowait(entry),
    )

    # Initialize log generator for simulation mode
    if settings.SIMULATION_MODE:
        app_state.log_generator = LogGenerator(
            log_file_path=settings.LOG_FILE_PATH,
            interval_min=settings.SIMULATION_INTERVAL_MIN,
            interval_max=settings.SIMULATION_INTERVAL_MAX,
        )
        app_state.log_generator.clear_log_file()

    # Start context engine
    await app_state.context_engine.start()

    # Start log processing task
    app_state._log_processor_task = asyncio.create_task(process_log_queue())

    # Start log ingestor to always read logs for dashboard
    if app_state.log_ingestor:
        asyncio.create_task(app_state.log_ingestor.start())
        print("📁 Log ingestor started - watching for logs")

    # Start log generator independently (like a real robot)
    if settings.SIMULATION_MODE and app_state.log_generator:
        app_state._generator_task = asyncio.create_task(
            run_simulation_continuous())
        print("🤖 Robot simulation started - generating logs continuously")

    print(f"{settings.APP_NAME} initialized successfully")

    yield

    # Cancel log processor
    if app_state._log_processor_task:
        app_state._log_processor_task.cancel()
        try:
            await app_state._log_processor_task
        except asyncio.CancelledError:
            pass

    # Cancel generator
    if hasattr(app_state, '_generator_task') and app_state._generator_task:
        app_state._generator_task.cancel()
        try:
            await app_state._generator_task
        except asyncio.CancelledError:
            pass

    # Shutdown
    print(f"Shutting down {settings.APP_NAME}...")

    if app_state.is_monitoring:
        await stop_monitoring()

    if app_state.context_engine:
        app_state.context_engine.stop()

    if app_state.log_ingestor:
        app_state.log_ingestor.stop()

    if app_state.log_generator:
        app_state.log_generator.stop()

    print("Shutdown complete")


async def process_log_queue():
    """Process log entries from the queue."""
    while True:
        try:
            log_entry: LogEntry = await app_state._log_queue.get()
            await handle_log_entry(log_entry)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error processing log entry: {e}")


async def handle_log_entry(log_entry: LogEntry):
    """Process a new log entry through the pipeline."""
    # Always broadcast log to WebSocket clients (even when not monitoring)
    await broadcast_to_websockets({
        "type": "log",
        "data": {
            "timestamp": log_entry.timestamp.isoformat(),
            "level": log_entry.level,
            "node": log_entry.node,
            "message": log_entry.message,
        }
    })

    # Only run analysis if monitoring is enabled
    if not app_state.is_monitoring:
        return

    # Add to context engine
    if app_state.context_engine:
        is_error = await app_state.context_engine.add(log_entry)

        # Broadcast context update
        context = await app_state.context_engine.get_context()
        await broadcast_to_websockets({
            "type": "context_update",
            "data": {
                "size": len(context),
                "entries": [{"level": e.level, "node": e.node, "message": e.message} for e in context[-5:]]
            }
        })

        # Run through detector for immediate feedback
        if app_state.error_detector:
            detection = app_state.error_detector.detect(log_entry)
            if detection.is_error:
                # Broadcast error detection
                await broadcast_to_websockets({
                    "type": "error_detected",
                    "data": {
                        "severity": detection.severity,
                        "error_type": detection.error_type,
                        "message": log_entry.message,
                        "node": log_entry.node,
                    }
                })


# FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="Real-time robot error log analysis AI agent",
    version="1.0.0",
    lifespan=lifespan,
)


# WebSocket endpoint for real-time dashboard
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time log streaming."""
    await websocket.accept()
    app_state.websocket_connections.add(websocket)

    try:
        # Send initial status
        await websocket.send_json({
            "type": "connected",
            "data": {
                "monitoring": app_state.is_monitoring,
                "simulation_mode": settings.SIMULATION_MODE,
            }
        })

        # Keep connection alive and handle client messages
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        app_state.websocket_connections.discard(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        app_state.websocket_connections.discard(websocket)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": utc_now().isoformat(),
        "monitoring": app_state.is_monitoring,
        "simulation_mode": settings.SIMULATION_MODE,
        "analysis_count": len(app_state.analysis_results),
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the real-time dashboard."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Robot Log Analysis - Live Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            height: 100vh;
            overflow: hidden;
        }
        .header {
            background: linear-gradient(90deg, #0f0f1a 0%, #1a1a2e 100%);
            padding: 15px 30px;
            border-bottom: 1px solid #2a2a4a;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 { color: #00d4ff; font-size: 1.5em; }
        .connection-status {
            display: flex;
            align-items: center;
            gap: 20px;
            font-size: 0.9em;
        }
        .status-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #ff4444;
        }
        .status-dot.connected { background: #00ff88; animation: pulse 1s infinite; }
        .status-dot.robot-dot.active { background: #00d4ff; animation: pulse 1s infinite; }
        .status-dot.agents-dot.active { background: #ffd700; animation: pulse 1s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .main-container {
            display: flex;
            height: calc(100vh - 70px);
        }
        .left-panel {
            width: 40%;
            background: #0f0f1a;
            border-right: 1px solid #2a2a4a;
            display: flex;
            flex-direction: column;
        }
        .panel-header {
            background: #1a1a2e;
            padding: 15px 20px;
            border-bottom: 1px solid #2a2a4a;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .panel-header h2 { color: #00d4ff; font-size: 1.1em; }
        .log-stats { display: flex; gap: 15px; font-size: 0.85em; }
        .log-stat { display: flex; align-items: center; gap: 5px; }
        .log-stat.error { color: #ff4444; }
        .log-stat.warn { color: #ffcc44; }
        .log-stat.info { color: #88ccff; }
        .log-stream {
            flex: 1;
            overflow-y: auto;
            padding: 10px;
            font-family: 'Courier New', monospace;
            font-size: 0.85em;
        }
        .log-entry {
            padding: 8px 12px;
            margin: 4px 0;
            border-radius: 6px;
            border-left: 3px solid transparent;
            animation: slideIn 0.3s ease;
            line-height: 1.4;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-20px); }
            to { opacity: 1; transform: translateX(0); }
        }
        .log-entry.error { background: rgba(255, 68, 68, 0.1); border-left-color: #ff4444; color: #ff8888; }
        .log-entry.warn { background: rgba(255, 204, 68, 0.1); border-left-color: #ffcc44; color: #ffdd88; }
        .log-entry.info { background: rgba(136, 204, 255, 0.1); border-left-color: #88ccff; color: #aaddff; }
        .log-entry .timestamp { color: #666; font-size: 0.9em; }
        .log-entry .level { font-weight: bold; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; }
        .log-entry.error .level { background: #ff4444; color: #fff; }
        .log-entry.warn .level { background: #ffcc44; color: #000; }
        .log-entry.info .level { background: #88ccff; color: #000; }
        .log-entry .node { color: #00d4ff; }
        .right-panel {
            width: 60%;
            background: #0a0a0f;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }
        .agents-section { padding: 20px; }
        .section-title { color: #ffd700; font-size: 1em; margin-bottom: 15px; text-transform: uppercase; letter-spacing: 1px; }
        .agent-network { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 30px; }
        .agent-card {
            background: linear-gradient(135deg, #1a1a2e 0%, #0f0f1a 100%);
            border: 2px solid #2a2a4a;
            border-radius: 12px;
            padding: 20px;
            transition: all 0.3s ease;
        }
        .agent-card:hover { border-color: #3a3a6a; transform: translateY(-2px); }
        .agent-card.active { border-color: #00d4ff; box-shadow: 0 0 20px rgba(0, 212, 255, 0.2); }
        .agent-card.processing { border-color: #ffd700; box-shadow: 0 0 20px rgba(255, 215, 0, 0.2); }
        .agent-card.detected { border-color: #ff4444; box-shadow: 0 0 20px rgba(255, 68, 68, 0.2); }
        .agent-card.analyzed { border-color: #00ff88; box-shadow: 0 0 20px rgba(0, 255, 136, 0.2); }
        .agent-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
        .agent-icon { width: 45px; height: 45px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 1.5em; background: #0f0f1a; border: 1px solid #2a2a4a; }
        .agent-card.active .agent-icon { background: rgba(0, 212, 255, 0.2); border-color: #00d4ff; }
        .agent-card.processing .agent-icon { background: rgba(255, 215, 0, 0.2); border-color: #ffd700; }
        .agent-card.detected .agent-icon { background: rgba(255, 68, 68, 0.2); border-color: #ff4444; }
        .agent-card.analyzed .agent-icon { background: rgba(0, 255, 136, 0.2); border-color: #00ff88; }
        .agent-name { font-weight: bold; color: #fff; font-size: 0.95em; }
        .agent-role { font-size: 0.8em; color: #888; }
        .agent-status { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #0f0f1a; border-radius: 6px; font-size: 0.85em; color: #888; }
        .agent-status .indicator { width: 8px; height: 8px; border-radius: 50%; background: #444; }
        .agent-card.active .agent-status .indicator { background: #00d4ff; animation: blink 0.5s infinite; }
        .agent-card.processing .agent-status .indicator { background: #ffd700; animation: blink 0.5s infinite; }
        .agent-card.detected .agent-status .indicator { background: #ff4444; }
        .agent-card.analyzed .agent-status .indicator { background: #00ff88; }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        .analysis-section { padding: 0 20px 20px; }
        .analysis-card {
            background: linear-gradient(135deg, #1a1a2e 0%, #0f0f1a 100%);
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 15px;
            border-left: 4px solid #00ff88;
            animation: fadeIn 0.5s ease;
        }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .analysis-card.critical { border-left-color: #ff4444; }
        .analysis-card.high { border-left-color: #ff8844; }
        .analysis-card.medium { border-left-color: #ffcc44; }
        .analysis-card.low { border-left-color: #66aa66; }
        .analysis-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .analysis-title { font-weight: bold; color: #fff; font-size: 1.1em; }
        .severity-badge { padding: 4px 12px; border-radius: 20px; font-size: 0.75em; font-weight: bold; text-transform: uppercase; }
        .severity-badge.critical { background: #ff4444; color: #fff; }
        .severity-badge.high { background: #ff8844; color: #fff; }
        .severity-badge.medium { background: #ffcc44; color: #000; }
        .severity-badge.low { background: #66aa66; color: #fff; }
        .category-badge { padding: 4px 10px; border-radius: 6px; font-size: 0.7em; font-weight: bold; text-transform: uppercase; margin-left: 8px; }
        .category-badge.infrastructure { background: #5a4fcf; color: #fff; }
        .category-badge.queue { background: #c45a11; color: #fff; }
        .category-badge.auth { background: #a62a2a; color: #fff; }
        .category-badge.performance { background: #2a7a4a; color: #fff; }
        .category-badge.external { background: #6b4c9a; color: #fff; }
        .category-badge.application { background: #2a5a8a; color: #fff; }
        .taxonomy-line { font-family: 'Courier New', monospace; font-size: 0.8em; color: #00d4ff; background: rgba(0,0,0,0.3); padding: 8px 12px; border-radius: 6px; margin: 8px 0; word-break: break-all; }
        .analysis-content { color: #aaa; font-size: 0.9em; line-height: 1.6; }
        .analysis-content strong { color: #ddd; }
        .actions-list { margin-top: 12px; padding-left: 20px; }
        .actions-list li { color: #88ccff; margin: 5px 0; }
        .analysis-meta { display: flex; gap: 20px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #2a2a4a; font-size: 0.85em; color: #666; }
        .controls { display: flex; gap: 15px; padding: 15px 20px; background: #1a1a2e; border-bottom: 1px solid #2a2a4a; }
        button { padding: 10px 25px; border: none; border-radius: 6px; font-size: 0.9em; cursor: pointer; transition: all 0.3s ease; font-weight: bold; }
        .btn-start { background: #00ff88; color: #0a0a0f; }
        .btn-start:hover { background: #00cc6a; }
        .btn-stop { background: #ff4444; color: #fff; }
        .btn-stop:hover { background: #cc3333; }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #0f0f1a; }
        ::-webkit-scrollbar-thumb { background: #2a2a4a; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #3a3a6a; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 Robot Log Analysis Dashboard</h1>
        <div class="connection-status">
            <div class="status-item">
                <span class="status-dot robot-dot" id="robot-dot"></span>
                <span id="robot-text">Robot: Disconnected</span>
            </div>
            <div class="status-item">
                <span class="status-dot agents-dot" id="agents-dot"></span>
                <span id="agents-text">Agents: Idle</span>
            </div>
        </div>
    </div>
    <div class="main-container">
        <div class="left-panel">
            <div class="panel-header">
                <h2>📜 Live Log Stream</h2>
                <div class="log-stats">
                    <div class="log-stat error"><span>●</span> <span id="error-count">0</span></div>
                    <div class="log-stat warn"><span>●</span> <span id="warn-count">0</span></div>
                    <div class="log-stat info"><span>●</span> <span id="info-count">0</span></div>
                </div>
            </div>
            <div class="log-stream" id="log-stream"></div>
        </div>
        <div class="right-panel">
            <div class="controls">
                <button class="btn-start" onclick="startMonitoring()">▶ Start Monitoring</button>
                <button class="btn-stop" onclick="stopMonitoring()">⏹ Stop</button>
            </div>
            <div class="agents-section">
                <div class="section-title">🔧 Auto-Detective Agents</div>
                <div class="agent-network">
                    <div class="agent-card" id="agent-ingestor">
                        <div class="agent-header">
                            <div class="agent-icon">👁</div>
                            <div><div class="agent-name">Log Ingestor</div><div class="agent-role">File Watcher</div></div>
                        </div>
                        <div class="agent-status"><span class="indicator"></span><span class="status-text">Waiting...</span></div>
                    </div>
                    <div class="agent-card" id="agent-context">
                        <div class="agent-header">
                            <div class="agent-icon">📦</div>
                            <div><div class="agent-name">Context Engine</div><div class="agent-role">Sliding Window</div></div>
                        </div>
                        <div class="agent-status"><span class="indicator"></span><span class="status-text">Buffer: 0</span></div>
                    </div>
                    <div class="agent-card" id="agent-detector">
                        <div class="agent-header">
                            <div class="agent-icon">🔍</div>
                            <div><div class="agent-name">Error Detector</div><div class="agent-role">Pattern Matcher</div></div>
                        </div>
                        <div class="agent-status"><span class="indicator"></span><span class="status-text">Scanning...</span></div>
                    </div>
                    <div class="agent-card" id="agent-analyzer">
                        <div class="agent-header">
                            <div class="agent-icon">🧠</div>
                            <div><div class="agent-name">AI Analyzer</div><div class="agent-role">GPT-3.5 Turbo</div></div>
                        </div>
                        <div class="agent-status"><span class="indicator"></span><span class="status-text">Ready</span></div>
                    </div>
                    <div class="agent-card" id="agent-correlator">
                        <div class="agent-header">
                            <div class="agent-icon">🔗</div>
                            <div><div class="agent-name">Correlator</div><div class="agent-role">Pattern Linker</div></div>
                        </div>
                        <div class="agent-status"><span class="indicator"></span><span class="status-text">Idle</span></div>
                    </div>
                    <div class="agent-card" id="agent-reporter">
                        <div class="agent-header">
                            <div class="agent-icon">📊</div>
                            <div><div class="agent-name">Reporter</div><div class="agent-role">Result Formatter</div></div>
                        </div>
                        <div class="agent-status"><span class="indicator"></span><span class="status-text">Idle</span></div>
                    </div>
                </div>
            </div>
            <div class="analysis-section">
                <div class="section-title">✅ Auto-Analysis Results</div>
                <div id="analysis-results"></div>
            </div>
        </div>
    </div>
    <script>
        let ws = null;
        let stats = { error: 0, warn: 0, info: 0 };
        let reconnectInterval = null;
        
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onopen = () => {
                console.log('WebSocket connected');
                document.getElementById('robot-dot').classList.add('active');
                document.getElementById('robot-text').textContent = 'Robot: Running';
                clearInterval(reconnectInterval);
            };
            
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                handleMessage(msg);
            };
            
            ws.onclose = () => {
                console.log('WebSocket disconnected');
                document.getElementById('robot-dot').classList.remove('active');
                document.getElementById('robot-text').textContent = 'Robot: Disconnected';
                document.getElementById('agents-dot').classList.remove('active');
                document.getElementById('agents-text').textContent = 'Agents: Idle';
                reconnectInterval = setInterval(connectWebSocket, 3000);
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        }
        
        function setAgentState(agentId, state, message) {
            const agent = document.getElementById(agentId);
            agent.className = 'agent-card ' + state;
            agent.querySelector('.status-text').textContent = message;
        }
        
        function resetAgents() {
            ['agent-ingestor', 'agent-context', 'agent-detector', 'agent-analyzer', 'agent-correlator', 'agent-reporter'].forEach(id => {
                const agent = document.getElementById(id);
                agent.className = 'agent-card';
            });
            document.querySelector('#agent-ingestor .status-text').textContent = 'Waiting...';
            document.querySelector('#agent-context .status-text').textContent = 'Buffer: 0';
            document.querySelector('#agent-detector .status-text').textContent = 'Scanning...';
            document.querySelector('#agent-analyzer .status-text').textContent = 'Ready';
            document.querySelector('#agent-correlator .status-text').textContent = 'Idle';
            document.querySelector('#agent-reporter .status-text').textContent = 'Idle';
        }
        
        function addLogEntry(level, node, message) {
            const container = document.getElementById('log-stream');
            const entry = document.createElement('div');
            entry.className = `log-entry ${level.toLowerCase()}`;
            const timestamp = new Date().toISOString().replace('T', ' ').substring(0, 23);
            entry.innerHTML = `<span class="timestamp">${timestamp}</span> <span class="level">${level}</span> <span class="node">[${node}]</span> ${message}`;
            container.insertBefore(entry, container.firstChild);
            while (container.children.length > 100) container.removeChild(container.lastChild);
            stats[level.toLowerCase()]++;
            document.getElementById('error-count').textContent = stats.error;
            document.getElementById('warn-count').textContent = stats.warn;
            document.getElementById('info-count').textContent = stats.info;
            setAgentState('agent-ingestor', 'active', 'Reading...');
            setTimeout(() => setAgentState('agent-ingestor', '', 'Waiting...'), 300);
        }
        
        function addAnalysisResult(data) {
            const container = document.getElementById('analysis-results');
            const card = document.createElement('div');
            card.className = `analysis-card ${data.severity}`;
            const taxonomy = data.taxonomy || {};
            const taxonomyLine = data.taxonomy_line || '';
            const cat = (taxonomy.category || '').toLowerCase();
            const categoryBadge = taxonomy.category
                ? `<span class="category-badge ${cat}">${taxonomy.category}</span>`
                : '';
            const taxonomyBlock = taxonomyLine
                ? `<div class="taxonomy-line" title="SKILL.md classification">${escapeHtml(taxonomyLine)}</div>`
                : '';
            card.innerHTML = `
                <div class="analysis-header">
                    <div class="analysis-title">${escapeHtml(data.error_type)}${categoryBadge}</div>
                    <span class="severity-badge ${data.severity}">${data.severity}</span>
                </div>
                ${taxonomyBlock}
                <div class="analysis-content">
                    <strong>Root Cause:</strong> ${escapeHtml(data.root_cause)}<br><br>
                    <strong>Corrective Actions:</strong>
                    <ul class="actions-list">${(data.corrective_actions || []).map(a => `<li>${escapeHtml(a)}</li>`).join('')}</ul>
                </div>
                <div class="analysis-meta">
                    <span>🤖 Confidence: ${Math.round((data.confidence || 0) * 100)}%</span>
                    <span>📦 Affected: ${(data.affected_systems || []).join(', ') || 'N/A'}</span>
                </div>
            `;
            container.insertBefore(card, container.firstChild);
            while (container.children.length > 10) container.removeChild(container.lastChild);
        }
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        let isMonitoring = false;
        
        function updateButtonStates() {
            const startBtn = document.querySelector('.btn-start');
            const stopBtn = document.querySelector('.btn-stop');
            
            if (isMonitoring) {
                startBtn.style.opacity = '0.5';
                startBtn.style.cursor = 'not-allowed';
                stopBtn.style.opacity = '1';
                stopBtn.style.cursor = 'pointer';
            } else {
                startBtn.style.opacity = '1';
                startBtn.style.cursor = 'pointer';
                stopBtn.style.opacity = '0.5';
                stopBtn.style.cursor = 'not-allowed';
            }
        }
        
        async function startMonitoring() {
            if (isMonitoring) return;
            try {
                const response = await fetch('/monitor/start', { method: 'POST' });
                const data = await response.json();
                if (data.status === 'started' || data.status === 'already_running') {
                    isMonitoring = true;
                    updateButtonStates();
                    document.getElementById('agents-dot').classList.add('active');
                    document.getElementById('agents-text').textContent = 'Agents: Analyzing';
                }
            } catch (e) {
                console.error('Failed to start monitoring:', e);
            }
        }
        
        async function stopMonitoring() {
            if (!isMonitoring) return;
            try {
                const response = await fetch('/monitor/stop', { method: 'POST' });
                const data = await response.json();
                if (data.status === 'stopped') {
                    isMonitoring = false;
                    updateButtonStates();
                    document.getElementById('agents-dot').classList.remove('active');
                    document.getElementById('agents-text').textContent = 'Agents: Idle';
                }
            } catch (e) {
                console.error('Failed to stop monitoring:', e);
            }
        }
        
        function handleMessage(msg) {
            switch(msg.type) {
                case 'connected':
                    isMonitoring = msg.data.monitoring;
                    updateButtonStates();
                    if (isMonitoring) {
                        document.getElementById('agents-dot').classList.add('active');
                        document.getElementById('agents-text').textContent = 'Agents: Analyzing';
                    }
                    break;
                case 'log':
                    addLogEntry(msg.data.level, msg.data.node, msg.data.message);
                    break;
                case 'context_update':
                    setAgentState('agent-context', 'active', `Buffer: ${msg.data.size}`);
                    break;
                case 'error_detected':
                    setAgentState('agent-detector', 'detected', `Error: ${msg.data.error_type}`);
                    break;
                case 'analysis_start':
                    setAgentState('agent-analyzer', 'processing', 'Analyzing...');
                    setAgentState('agent-correlator', 'active', 'Linking...');
                    setAgentState('agent-reporter', 'active', 'Formatting...');
                    break;
                case 'analysis_complete':
                    addAnalysisResult(msg.data);
                    setAgentState('agent-analyzer', 'analyzed', 'Complete');
                    setAgentState('agent-correlator', 'analyzed', 'Done');
                    setAgentState('agent-reporter', 'analyzed', 'Reported');
                    setTimeout(() => resetAgents(), 2000);
                    break;
            }
        }
        
        // Initialize button states
        updateButtonStates();
        connectWebSocket();
    </script>
</body>
</html>"""


@app.post("/monitor/start")
async def start_monitoring():
    """Start analysis agents monitoring (log generator runs independently)."""
    if app_state.is_monitoring:
        return {"status": "already_running", "message": "Monitoring is already active"}

    app_state.is_monitoring = True

    # Start log ingestor to read logs
    if app_state.log_ingestor:
        asyncio.create_task(app_state.log_ingestor.start())

    return {
        "status": "started",
        "mode": "analysis",
        "message": "Agents now analyzing logs (robot simulation continues independently)",
    }


@app.post("/monitor/stop")
async def stop_monitoring():
    """Stop analysis agents (log generator and ingestor continue running)."""
    if not app_state.is_monitoring:
        return {"status": "not_running", "message": "Monitoring is not active"}

    app_state.is_monitoring = False

    # Clear context engine when stopping analysis
    if app_state.context_engine:
        await app_state.context_engine.clear()

    return {"status": "stopped", "message": "Agents stopped (robot simulation continues)"}


@app.get("/analysis")
async def get_analysis(
    limit: int = Query(10, ge=1, le=100),
    severity: Optional[str] = Query(
        None, pattern="^(critical|high|medium|low)$"),
):
    """Get analysis results."""
    results = app_state.analysis_results

    if severity:
        results = [r for r in results if r.severity == severity]

    # Sort by timestamp descending
    results = sorted(results, key=lambda x: x.timestamp, reverse=True)

    return {
        "count": len(results),
        "results": [r.to_dict() for r in results[:limit]],
    }


@app.get("/analysis/{analysis_id}")
async def get_analysis_by_id(analysis_id: str):
    """Get a specific analysis result by ID."""
    for result in app_state.analysis_results:
        if result.id == analysis_id:
            return result.to_dict()

    raise HTTPException(status_code=404, detail="Analysis not found")


@app.get("/stats")
async def get_stats():
    """Get system statistics."""
    stats = {
        "monitoring": app_state.is_monitoring,
        "simulation_mode": settings.SIMULATION_MODE,
        "analysis_results": len(app_state.analysis_results),
    }

    if app_state.error_detector:
        stats["detection"] = app_state.error_detector.get_stats()

    if app_state.analyzer:
        stats["analyzer"] = app_state.analyzer.get_stats()

    if app_state.context_engine:
        stats["context"] = app_state.context_engine.get_stats()

    return stats


@app.delete("/analysis")
async def clear_analysis():
    """Clear all analysis results."""
    count = len(app_state.analysis_results)
    app_state.analysis_results.clear()
    return {"cleared": count}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "monitor_start": "POST /monitor/start",
            "monitor_stop": "POST /monitor/stop",
            "analysis": "GET /analysis",
            "analysis_by_id": "GET /analysis/{id}",
            "stats": "GET /stats",
            "clear": "DELETE /analysis",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
    )
