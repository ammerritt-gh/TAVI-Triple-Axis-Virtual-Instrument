"""
Base Dock - Abstract base class for dock widgets.
"""
import tkinter as tk
from tkinter import ttk
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict


class BaseDock(ABC):
    """
    Abstract base class for dock widgets.
    
    Each dock represents a logical grouping of related controls
    in the GUI (e.g., instrument configuration, scan controls, etc.).
    """
    
    def __init__(self, parent: tk.Widget, **kwargs):
        """
        Initialize the dock.
        
        Args:
            parent: Parent tkinter widget
            **kwargs: Additional configuration options
        """
        self.parent = parent
        self.frame = ttk.Frame(parent, padding="10")
        self._callbacks: Dict[str, Callable] = {}
        
        # Create the dock content
        self._create_widgets()
    
    @abstractmethod
    def _create_widgets(self):
        """Create the widgets for this dock. Must be implemented by subclasses."""
        pass
    
    def grid(self, **kwargs):
        """Grid the dock frame."""
        self.frame.grid(**kwargs)
    
    def pack(self, **kwargs):
        """Pack the dock frame."""
        self.frame.pack(**kwargs)
    
    def place(self, **kwargs):
        """Place the dock frame."""
        self.frame.place(**kwargs)
    
    def register_callback(self, event_name: str, callback: Callable):
        """Register a callback for an event."""
        self._callbacks[event_name] = callback
    
    def _trigger_callback(self, event_name: str, *args, **kwargs):
        """Trigger a registered callback."""
        if event_name in self._callbacks:
            try:
                self._callbacks[event_name](*args, **kwargs)
            except Exception as e:
                print(f"Error in callback {event_name}: {e}")
    
    @staticmethod
    def bind_update_events(widget: tk.Widget, update_function: Callable, *args):
        """
        Bind FocusOut and Return events to trigger an update function.
        
        Args:
            widget: The widget to bind events to
            update_function: Function to call on events
            *args: Additional arguments to pass to update_function
        """
        widget.bind("<FocusOut>", lambda event: update_function(*args))
        widget.bind("<Return>", lambda event: update_function(*args))


class DockSection(ttk.LabelFrame):
    """
    A labeled section within a dock.
    
    Provides a visual grouping for related controls.
    """
    
    def __init__(self, parent: tk.Widget, title: str, **kwargs):
        super().__init__(parent, text=title, padding="5", **kwargs)
