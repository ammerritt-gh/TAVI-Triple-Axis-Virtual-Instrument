"""
Output Dock - Message center for user feedback.

Displays log messages, status updates, and simulation output.
"""
import tkinter as tk
from tkinter import ttk
from typing import Optional

from .base_dock import BaseDock


class OutputDock(BaseDock):
    """Dock for output messages and status."""
    
    def __init__(self, parent: tk.Widget, **kwargs):
        super().__init__(parent, **kwargs)
    
    def _create_widgets(self):
        """Create output widgets."""
        main_frame = ttk.Frame(self.frame)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(main_frame, text="Output", 
                  font=("Arial", 10, "bold")).pack(anchor="w")
        
        # Text widget with scrollbar
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.text = tk.Text(text_frame, wrap=tk.WORD, height=15, width=60)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.config(yscrollcommand=scrollbar.set)
        
        # Progress frame
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=5)
        
        # Progress bar
        self.progress_bar = ttk.Progressbar(
            progress_frame, 
            orient=tk.HORIZONTAL, 
            length=200, 
            mode='determinate'
        )
        self.progress_bar.pack(side=tk.LEFT, padx=5)
        
        # Progress label
        self.progress_label = ttk.Label(progress_frame, text="0% (0/0)")
        self.progress_label.pack(side=tk.LEFT, padx=5)
        
        # Remaining time
        self.time_label = ttk.Label(progress_frame, text="")
        self.time_label.pack(side=tk.LEFT, padx=10)
        
        # Counts frame
        counts_frame = ttk.Frame(main_frame)
        counts_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(counts_frame, text="Max counts:").pack(side=tk.LEFT)
        self.max_counts_label = ttk.Label(counts_frame, text="0")
        self.max_counts_label.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(counts_frame, text="Total counts:").pack(side=tk.LEFT, padx=(20, 0))
        self.total_counts_label = ttk.Label(counts_frame, text="0")
        self.total_counts_label.pack(side=tk.LEFT, padx=5)
        
        # Clear button
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=5)
        
        self.clear_button = ttk.Button(
            button_frame,
            text="Clear Output",
            command=self.clear
        )
        self.clear_button.pack(side=tk.LEFT)
    
    def log(self, message: str, target: str = 'both'):
        """
        Add a message to the output.
        
        Args:
            message: The message to display
            target: 'GUI', 'console', or 'both'
        """
        if target in ('both', 'GUI'):
            self.text.insert(tk.END, message + '\n')
            self.text.see(tk.END)
        if target in ('both', 'console'):
            print(message)
    
    def clear(self):
        """Clear all output text."""
        self.text.delete(1.0, tk.END)
    
    def update_progress(self, current: int, total: int):
        """Update the progress bar and label."""
        if total > 0:
            percentage = int(current * 100 / total)
            self.progress_bar["value"] = percentage
            self.progress_label.config(text=f"{percentage}% ({current}/{total})")
        else:
            self.progress_bar["value"] = 0
            self.progress_label.config(text="0% (0/0)")
    
    def update_remaining_time(self, remaining_time: str):
        """Update the remaining time display."""
        self.time_label.config(text=f"Remaining: {remaining_time}")
    
    def update_counts(self, max_counts: float, total_counts: float):
        """Update the counts display."""
        self.max_counts_label.config(text=str(int(max_counts)))
        self.total_counts_label.config(text=str(int(total_counts)))
    
    def reset_progress(self):
        """Reset progress indicators."""
        self.progress_bar["value"] = 0
        self.progress_label.config(text="0% (0/0)")
        self.time_label.config(text="")
        self.max_counts_label.config(text="0")
        self.total_counts_label.config(text="0")
