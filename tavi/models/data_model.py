"""
Data Model - Holds the state of data input/output settings.
Includes output folder selection and data loading configuration.
"""
from typing import Dict, Any, Optional, List
from .base_model import BaseModel, Observable
import os


class DataModel(BaseModel):
    """
    Model for data input/output configuration state.
    
    This includes:
    - Output folder selection
    - Actual output folder path (may be incremented)
    - Data loading folder
    - Scan results and progress
    """
    
    def __init__(self):
        super().__init__()
        
        # Output settings
        self.output_folder = Observable("")  # Target output folder
        self.actual_output_folder = Observable("")  # Actual folder used (may have suffix)
        
        # Load settings
        self.load_folder = Observable("")  # Folder to load data from
        
        # Scan progress
        self.current_scan = Observable(0)  # Current scan number
        self.total_scans = Observable(0)   # Total number of scans
        self.max_counts = Observable(0)     # Maximum counts seen
        self.total_counts = Observable(0)   # Total counts accumulated
        
        # Timing
        self.remaining_time = Observable("")  # Estimated remaining time
        
        # Messages/log
        self.messages: List[str] = []
        
    def add_message(self, message: str):
        """Add a message to the log."""
        self.messages.append(message)
        self.notify_observers("messages", None, message)
    
    def clear_messages(self):
        """Clear all messages."""
        self.messages = []
        self.notify_observers("messages_cleared", None, None)
    
    def get_progress_percentage(self) -> int:
        """Get the current progress as a percentage."""
        total = self.total_scans.get()
        if total <= 0:
            return 0
        return int(self.current_scan.get() * 100 / total)
    
    def reset_progress(self):
        """Reset scan progress counters."""
        self.current_scan.set(0)
        self.total_scans.set(0)
        self.max_counts.set(0)
        self.total_counts.set(0)
        self.remaining_time.set("")
    
    def update_counts(self, counts: float):
        """Update counts with a new measurement."""
        if counts > self.max_counts.get():
            self.max_counts.set(counts)
        self.total_counts.set(self.total_counts.get() + counts)
    
    def ensure_output_directory(self) -> str:
        """Ensure the base output directory exists and return its path."""
        base_dir = os.path.join(os.getcwd(), "output")
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        return base_dir
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize data model state to dictionary."""
        return {
            "output_folder": self.output_folder.get(),
            "load_folder": self.load_folder.get(),
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """Load data model state from dictionary."""
        if "output_folder" in data:
            self.output_folder.set(data["output_folder"])
        if "load_folder" in data:
            self.load_folder.set(data["load_folder"])
