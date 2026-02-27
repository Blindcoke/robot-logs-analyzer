# Robot Log Analysis AI Agent

A real-time robot error log analysis system that detects errors in ROS (Robot Operating System) logs, explains root causes, and suggests corrective actions using AI.

## Features

- **Real-time Log Monitoring**: Watches log files and detects errors as they occur
- **AI-Powered Analysis**: Uses OpenAI GPT-3.5-turbo to analyze error context
- **Error Detection**: Pattern matching for 10+ ROS error types
- **Context Awareness**: Sliding window buffer captures error context
- **Structured Output**: JSON API with severity, root cause, and corrective actions
- **Simulation Mode**: Built-in ROS log generator for testing

## Architecture

```
Log Generator → Log File → Log Ingestor → Context Engine → Error Detector → OpenAI Analyzer → JSON Output
```

## Quick Start

### 1. Install Dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your OpenAI API key:
```
OPENAI_API_KEY=sk-your-key-here
```

### 3. Run the Server

```bash
python3 main.py
```

The API will be available at `http://localhost:8000`

### 4. Start Monitoring

```bash
curl -X POST http://localhost:8000/monitor/start
```

### 5. View Analysis Results

```bash
curl http://localhost:8000/analysis
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/monitor/start` | POST | Start log monitoring |
| `/monitor/stop` | POST | Stop log monitoring |
| `/analysis` | GET | Get analysis results |
| `/analysis/{id}` | GET | Get specific analysis |
| `/stats` | GET | System statistics |

## Configuration

Edit `.env` file:

```bash
# Log source
LOG_FILE_PATH=./logs/robot.log
SIMULATION_MODE=true  # Set to false for real log files

# AI Configuration
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-3.5-turbo

# Context window
CONTEXT_WINDOW_SIZE=50
CONTEXT_TIMEOUT_SEC=30
```

## Project Structure

```
robot-log-agent/
├── main.py                 # FastAPI application
├── config.py               # Configuration settings
├── requirements.txt        # Python dependencies
├── agents/
│   ├── log_ingestor.py     # File watcher for logs
│   ├── context_engine.py   # Sliding window context
│   ├── error_detector.py   # Pattern-based detection
│   └── analyzer.py         # OpenAI integration
├── models/
│   ├── log_entry.py        # Log entry data model
│   └── analysis.py         # Analysis result model
├── simulator/
│   └── log_generator.py    # ROS log simulator
└── tests/
    └── test_analyzer.py    # Unit tests
```

## Error Types Detected

- Transform Timeout
- Planning Failure
- Sensor Timeout
- Hardware Connection
- Joint Limit
- Collision Detected
- Navigation Failure
- Controller Error
- SLAM Error

## Testing

Run unit tests:

```bash
python3 -m pytest tests/test_analyzer.py -v
```

View generated logs:

```bash
tail -f logs/robot.log
```

## Production Usage

To use with real robot logs:

1. Set `SIMULATION_MODE=false` in `.env`
2. Set `LOG_FILE_PATH=/path/to/your/robot.log`
3. Restart the server

The system will monitor your actual log file for errors.

## License

MIT
