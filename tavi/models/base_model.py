"""
Base Model class for MVVM architecture.
Provides observable state management with change notifications.
"""
from typing import Any, Callable, Dict, List, Optional


class Observable:
    """A simple observable value that notifies subscribers when changed."""
    
    def __init__(self, initial_value: Any = None):
        self._value = initial_value
        self._callbacks: List[Callable[[Any, Any], None]] = []
    
    @property
    def value(self) -> Any:
        return self._value
    
    @value.setter
    def value(self, new_value: Any):
        if self._value != new_value:
            old_value = self._value
            self._value = new_value
            self._notify(old_value, new_value)
    
    def get(self) -> Any:
        """Get the current value."""
        return self._value
    
    def set(self, new_value: Any):
        """Set a new value."""
        self.value = new_value
    
    def subscribe(self, callback: Callable[[Any, Any], None]):
        """Subscribe to value changes. Callback receives (old_value, new_value)."""
        self._callbacks.append(callback)
    
    def unsubscribe(self, callback: Callable[[Any, Any], None]):
        """Unsubscribe from value changes."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def _notify(self, old_value: Any, new_value: Any):
        """Notify all subscribers of a value change."""
        for callback in self._callbacks:
            try:
                callback(old_value, new_value)
            except Exception as e:
                print(f"Error in observable callback: {e}")


class BaseModel:
    """
    Base class for all models in the MVVM architecture.
    Provides common functionality for state management.
    """
    
    def __init__(self):
        self._observers: Dict[str, List[Callable]] = {}
    
    def add_observer(self, property_name: str, callback: Callable):
        """Add an observer for a specific property."""
        if property_name not in self._observers:
            self._observers[property_name] = []
        self._observers[property_name].append(callback)
    
    def remove_observer(self, property_name: str, callback: Callable):
        """Remove an observer for a specific property."""
        if property_name in self._observers and callback in self._observers[property_name]:
            self._observers[property_name].remove(callback)
    
    def notify_observers(self, property_name: str, old_value: Any = None, new_value: Any = None):
        """Notify all observers of a property change."""
        if property_name in self._observers:
            for callback in self._observers[property_name]:
                try:
                    callback(old_value, new_value)
                except Exception as e:
                    print(f"Error notifying observer for {property_name}: {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize model state to dictionary for saving."""
        result = {}
        for key, value in self.__dict__.items():
            if not key.startswith('_'):
                if isinstance(value, Observable):
                    result[key] = value.get()
                elif isinstance(value, BaseModel):
                    result[key] = value.to_dict()
                else:
                    result[key] = value
        return result
    
    def from_dict(self, data: Dict[str, Any]):
        """Load model state from dictionary."""
        for key, value in data.items():
            if hasattr(self, key):
                attr = getattr(self, key)
                if isinstance(attr, Observable):
                    attr.set(value)
                elif isinstance(attr, BaseModel) and isinstance(value, dict):
                    attr.from_dict(value)
                else:
                    setattr(self, key, value)
