import asyncio
import random
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional


class LogGenerator:
    """Generates realistic ROS-style log entries for simulation."""

    # ROS nodes that commonly appear in logs
    NODES = [
        "/move_base",
        "/amcl",
        "/robot_state_publisher",
        "/joint_state_publisher",
        "/laser_scan_matcher",
        "/gmapping",
        "/navigation",
        "/controller_manager",
        "/hardware_interface",
        "/sensor_driver",
        "/camera_node",
        "/odometry",
        "/tf_broadcaster",
    ]

    # Normal operation messages
    NORMAL_MESSAGES = [
        "Robot state updated successfully",
        "Joint states published",
        "Laser scan received",
        "Odometry message processed",
        "Transform published: base_link -> laser",
        "Goal received: x=1.5, y=2.0, theta=0.0",
        "Path computed successfully",
        "Velocity command sent",
        "Sensor data processed",
        "Heartbeat signal sent",
    ]

    # Warning messages
    WARNING_MESSAGES = [
        "Laser scan message delayed by 0.15s",
        "Costmap update frequency is low",
        "Controller oscillation detected",
        "Battery level below 30%",
        "Transform from map to odom is old",
        "Planning loop missed deadline",
        "Sensor data buffer nearly full",
        "CPU usage above 80%",
    ]

    # Error scenarios
    ERROR_SCENARIOS = [
        {
            "error": "Failed to get robot pose: Transform timeout",
            "context": [
                "Waiting for transform: map -> base_link",
                "Transform lookup failed after 5.0s",
            ],
            "type": "Transform Timeout",
        },
        {
            "error": "Navigation failed: Goal unreachable",
            "context": [
                "Planning to goal...",
                "No valid path found after 10 attempts",
                "Aborting navigation",
            ],
            "type": "Planning Failure",
        },
        {
            "error": "Laser scan topic not receiving data",
            "context": [
                "Subscribing to /scan topic",
                "No messages received for 5.0 seconds",
            ],
            "type": "Sensor Timeout",
        },
        {
            "error": "Exception in controller: Joint limit exceeded",
            "context": [
                "Processing joint command",
                "Joint 3 position: 2.1 (limit: 2.0)",
            ],
            "type": "Joint Limit",
        },
        {
            "error": "Connection refused: Unable to connect to hardware",
            "context": [
                "Initializing hardware interface",
                "Attempting connection to 192.168.1.100:502",
            ],
            "type": "Hardware Connection",
        },
        {
            "error": "Costmap collision: Robot in collision",
            "context": [
                "Updating costmap",
                "Footprint in collision at (1.2, 3.4)",
            ],
            "type": "Collision Detected",
        },
    ]

    def __init__(
        self,
        log_file_path: str = "./logs/robot.log",
        interval_min: float = 2.0,
        interval_max: float = 5.0,
        error_probability: float = 0.15,
    ):
        self.log_file_path = Path(log_file_path)
        self.interval_min = interval_min
        self.interval_max = interval_max
        self.error_probability = error_probability
        self._running = False
        self._error_in_progress = False
        self._current_scenario = None
        self._scenario_step = 0

        # Ensure log directory exists
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

    def _format_ros_log(
        self,
        level: str,
        node: str,
        message: str,
        timestamp: Optional[datetime] = None
    ) -> str:
        """Format a log entry in ROS style."""
        if timestamp is None:
            timestamp = datetime.now()

        ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        return f"[{level}] [{ts_str}] [{node}]: {message}"

    def _generate_normal_log(self) -> str:
        """Generate a normal operation log entry."""
        node = random.choice(self.NODES)
        message = random.choice(self.NORMAL_MESSAGES)
        level = random.choices(
            ["INFO", "DEBUG"],
            weights=[0.8, 0.2]
        )[0]
        return self._format_ros_log(level, node, message)

    def _generate_warning_log(self) -> str:
        """Generate a warning log entry."""
        node = random.choice(self.NODES)
        message = random.choice(self.WARNING_MESSAGES)
        return self._format_ros_log("WARN", node, message)

    def _generate_error_log(self) -> tuple[str, str]:
        """Generate an error log entry. Returns (log_line, error_type)."""
        if not self._error_in_progress:
            # Start a new error scenario
            self._current_scenario = random.choice(self.ERROR_SCENARIOS)
            self._error_in_progress = True
            self._scenario_step = 0

        scenario = self._current_scenario
        node = random.choice(
            ["/move_base", "/amcl", "/controller_manager", "/hardware_interface"])

        if self._scenario_step < len(scenario["context"]):
            # Generate context message
            message = scenario["context"][self._scenario_step]
            level = "WARN" if self._scenario_step == 0 else "INFO"
            self._scenario_step += 1
            return self._format_ros_log(level, node, message), scenario["type"]
        else:
            # Generate the actual error
            message = scenario["error"]
            self._error_in_progress = False
            self._current_scenario = None
            return self._format_ros_log("ERROR", node, message), scenario["type"]

    async def generate(self) -> AsyncGenerator[str, None]:
        """Generate log entries asynchronously."""
        self._running = True

        while self._running:
            # Determine what type of log to generate
            if self._error_in_progress:
                # Continue the error scenario
                log_line, _ = self._generate_error_log()
            elif random.random() < self.error_probability:
                # Start a new error scenario
                log_line, _ = self._generate_error_log()
            elif random.random() < 0.2:
                # Generate a warning
                log_line = self._generate_warning_log()
            else:
                # Generate normal operation log
                log_line = self._generate_normal_log()

            # Write to file
            with open(self.log_file_path, "a") as f:
                f.write(log_line + "\n")

            yield log_line

            # Wait before next entry
            interval = random.uniform(self.interval_min, self.interval_max)
            await asyncio.sleep(interval)

    async def start(self) -> None:
        """Start generating logs to file."""
        self._running = True
        print(f"Log generator started. Writing to: {self.log_file_path}")

        async for _ in self.generate():
            pass

    def stop(self) -> None:
        """Stop the log generator."""
        self._running = False
        print("Log generator stopped.")

    def clear_log_file(self) -> None:
        """Clear the log file."""
        if self.log_file_path.exists():
            self.log_file_path.write_text("")
            print(f"Cleared log file: {self.log_file_path}")


# For testing the generator directly
if __name__ == "__main__":
    generator = LogGenerator()
    generator.clear_log_file()

    try:
        asyncio.run(generator.start())
    except KeyboardInterrupt:
        generator.stop()
