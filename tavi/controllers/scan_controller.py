"""
Scan Controller - Handles asynchronous execution of McStas simulations.
Provides the bridge between the GUI state and the McStas instrument.
"""
import threading
import queue
import time
import datetime
import os
from typing import Callable, Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class ScanResult:
    """Result from a single scan point."""
    scan_index: int
    scan_point: List[float]
    intensity: float
    intensity_error: float
    counts: float
    output_folder: str
    success: bool
    error_message: str = ""


class ScanController:
    """
    Controller for managing scan execution.
    
    Handles:
    - Asynchronous simulation execution
    - Progress tracking
    - Batch scan management
    - Stop/cancel functionality
    """
    
    def __init__(self):
        self._stop_flag = False
        self._running = False
        self._simulation_thread: Optional[threading.Thread] = None
        self._result_queue: queue.Queue = queue.Queue()
        
        # Callbacks
        self._on_progress: Optional[Callable[[int, int], None]] = None
        self._on_message: Optional[Callable[[str], None]] = None
        self._on_counts_update: Optional[Callable[[float, float], None]] = None
        self._on_time_update: Optional[Callable[[str], None]] = None
        self._on_scan_complete: Optional[Callable[[ScanResult], None]] = None
        self._on_all_complete: Optional[Callable[[str], None]] = None
        
    @property
    def is_running(self) -> bool:
        """Check if a simulation is currently running."""
        return self._running
    
    def set_progress_callback(self, callback: Callable[[int, int], None]):
        """Set callback for progress updates. Args: (current, total)"""
        self._on_progress = callback
    
    def set_message_callback(self, callback: Callable[[str], None]):
        """Set callback for log messages."""
        self._on_message = callback
    
    def set_counts_callback(self, callback: Callable[[float, float], None]):
        """Set callback for counts updates. Args: (max_counts, total_counts)"""
        self._on_counts_update = callback
    
    def set_time_callback(self, callback: Callable[[str], None]):
        """Set callback for remaining time updates."""
        self._on_time_update = callback
    
    def set_scan_complete_callback(self, callback: Callable[[ScanResult], None]):
        """Set callback for individual scan completion."""
        self._on_scan_complete = callback
    
    def set_all_complete_callback(self, callback: Callable[[str], None]):
        """Set callback when all scans are complete."""
        self._on_all_complete = callback
    
    def _log(self, message: str):
        """Log a message using the callback if set."""
        if self._on_message:
            self._on_message(message)
        print(message)
    
    def stop(self):
        """Stop the current simulation."""
        self._stop_flag = True
        self._log("Stop requested...")
    
    def run_simulation(self, 
                       puma_instrument,
                       scan_parameters: Dict[str, Any],
                       scan_points: List[List[float]],
                       output_folder: str,
                       run_puma_func: Callable,
                       read_detector_func: Callable,
                       write_params_func: Callable,
                       letter_encode_func: Callable):
        """
        Start a simulation run in a separate thread.
        
        Args:
            puma_instrument: The PUMA instrument instance
            scan_parameters: Dictionary of scan parameters
            scan_points: List of scan points to execute
            output_folder: Base output folder path
            run_puma_func: Function to run PUMA instrument
            read_detector_func: Function to read detector data
            write_params_func: Function to write parameters to file
            letter_encode_func: Function to encode numbers for folder names
        """
        if self._running:
            self._log("Simulation already running!")
            return
        
        self._stop_flag = False
        self._running = True
        
        self._simulation_thread = threading.Thread(
            target=self._run_simulation_worker,
            args=(puma_instrument, scan_parameters, scan_points, output_folder,
                  run_puma_func, read_detector_func, write_params_func, letter_encode_func)
        )
        self._simulation_thread.start()
    
    def _run_simulation_worker(self,
                                puma_instrument,
                                scan_parameters: Dict[str, Any],
                                scan_points: List[List[float]],
                                output_folder: str,
                                run_puma_func: Callable,
                                read_detector_func: Callable,
                                write_params_func: Callable,
                                letter_encode_func: Callable):
        """Worker function that runs in a separate thread."""
        try:
            total_scans = len(scan_points)
            max_counts = 0
            total_counts = 0
            
            start_time = time.time()
            total_time = 0
            last_iteration_time = start_time
            
            # Apply scan parameters to instrument
            puma_instrument.K_fixed = scan_parameters.get("K_fixed", "Kf Fixed")
            puma_instrument.fixed_E = float(scan_parameters.get("fixed_E", 14.7))
            puma_instrument.monocris = scan_parameters.get("monocris", "PG[002]")
            puma_instrument.anacris = scan_parameters.get("anacris", "PG[002]")
            puma_instrument.alpha_1 = scan_parameters.get("alpha_1", 40)
            puma_instrument.alpha_2 = scan_parameters.get("alpha_2", [40])
            puma_instrument.alpha_3 = scan_parameters.get("alpha_3", 30)
            puma_instrument.alpha_4 = scan_parameters.get("alpha_4", 30)
            puma_instrument.rhmfac = scan_parameters.get("rhmfac", 1)
            puma_instrument.rvmfac = scan_parameters.get("rvmfac", 1)
            puma_instrument.rhafac = scan_parameters.get("rhafac", 1)
            puma_instrument.NMO_installed = scan_parameters.get("NMO_installed", "None")
            puma_instrument.V_selector_installed = scan_parameters.get("V_selector_installed", False)
            
            number_neutrons = scan_parameters.get("number_neutrons", 1e8)
            diagnostic_mode = scan_parameters.get("diagnostic_mode", True)
            diagnostic_settings = scan_parameters.get("diagnostic_settings", {})
            scan_mode = scan_parameters.get("scan_mode", "momentum")
            
            for i, scan_point in enumerate(scan_points):
                if self._stop_flag:
                    self._log("Simulation stopped by user.")
                    break
                
                # Extract scan values
                if scan_mode == "momentum":
                    qx, qy, qz, deltaE = scan_point[:4]
                    angles_array, error_flags = puma_instrument.calculate_angles(
                        qx, qy, qz, deltaE, puma_instrument.fixed_E,
                        puma_instrument.K_fixed, puma_instrument.monocris, puma_instrument.anacris
                    )
                    if not error_flags:
                        mtt, stt, sth, saz, att = angles_array
                        puma_instrument.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
                elif scan_mode == "rlu":
                    H, K, L, deltaE = scan_point[:4]
                    # Convert HKL to Q using lattice parameters from scan_params
                    # Note: This requires lattice parameters to be passed in scan_params
                    lattice_a = scan_params.get("lattice_a", 4.05)
                    lattice_b = scan_params.get("lattice_b", 4.05)
                    lattice_c = scan_params.get("lattice_c", 4.05)
                    lattice_alpha = scan_params.get("lattice_alpha", 90.0)
                    lattice_beta = scan_params.get("lattice_beta", 90.0)
                    lattice_gamma = scan_params.get("lattice_gamma", 90.0)
                    
                    # Import reciprocal space model for conversion
                    from tavi.models.reciprocal_space_model import ReciprocalSpaceModel
                    recip = ReciprocalSpaceModel()
                    recip.H.set(H)
                    recip.K.set(K)
                    recip.L.set(L)
                    try:
                        recip.update_Q_from_HKL(lattice_a, lattice_b, lattice_c,
                                                lattice_alpha, lattice_beta, lattice_gamma)
                        qx, qy, qz = recip.qx.get(), recip.qy.get(), recip.qz.get()
                    except ValueError as e:
                        self._log(f"HKL to Q conversion failed: {e}")
                        qx, qy, qz = 0, 0, 0
                        error_flags.append("hkl_conversion")
                    
                    angles_array, calc_errors = puma_instrument.calculate_angles(
                        qx, qy, qz, deltaE, puma_instrument.fixed_E,
                        puma_instrument.K_fixed, puma_instrument.monocris, puma_instrument.anacris
                    )
                    error_flags.extend(calc_errors)
                    if not error_flags:
                        mtt, stt, sth, saz, att = angles_array
                        puma_instrument.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
                else:  # Angle mode
                    A1, A2, A3, A4 = scan_point[:4]
                    puma_instrument.set_angles(A1=A1, A2=A2, A3=A3, A4=A4)
                    error_flags = []
                    deltaE = 0
                
                # Calculate crystal bending
                rhm, rvm, rha, rva = puma_instrument.calculate_crystal_bending(
                    puma_instrument.rhmfac, puma_instrument.rvmfac,
                    puma_instrument.rhafac, puma_instrument.A1, puma_instrument.A4
                )
                puma_instrument.set_crystal_bending(rhm=rhm, rvm=rvm, rha=rha, rva=rva)
                
                # Generate scan folder name
                scan_description = self._generate_scan_folder_name(
                    scan_point, scan_mode, letter_encode_func
                )
                scan_folder = os.path.join(output_folder, "_".join(scan_description))
                
                # Log scan start
                if scan_mode == "momentum":
                    self._log(f"Scan {i+1}/{total_scans}: qx={qx}, qy={qy}, qz={qz}, deltaE={deltaE}")
                elif scan_mode == "rlu":
                    self._log(f"Scan {i+1}/{total_scans}: H={H}, K={K}, L={L}, deltaE={deltaE}")
                else:
                    self._log(f"Scan {i+1}/{total_scans}: A1={A1}, A2={A2}, A3={A3}, A4={A4}")
                
                # Run the simulation
                result = ScanResult(
                    scan_index=i,
                    scan_point=scan_point,
                    intensity=0,
                    intensity_error=0,
                    counts=0,
                    output_folder=scan_folder,
                    success=False
                )
                
                if not error_flags:
                    try:
                        data, run_error_flags = run_puma_func(
                            puma_instrument, number_neutrons, deltaE,
                            diagnostic_mode, diagnostic_settings, scan_folder, i
                        )
                        
                        if not run_error_flags:
                            # Write parameters and read results
                            intensity, intensity_error, counts = read_detector_func(scan_folder)
                            
                            result.intensity = intensity
                            result.intensity_error = intensity_error
                            result.counts = counts
                            result.success = True
                            
                            max_counts = max(max_counts, counts)
                            total_counts += counts
                            
                            self._log(f"Counts: {int(counts)}")
                        else:
                            result.error_message = f"Run errors: {run_error_flags}"
                            self._log(f"Scan failed: {run_error_flags}")
                    except Exception as e:
                        result.error_message = str(e)
                        self._log(f"Scan error: {e}")
                else:
                    result.error_message = f"Angle calculation errors: {error_flags}"
                    self._log(f"Skipping scan due to errors: {error_flags}")
                
                # Notify callbacks
                if self._on_progress:
                    self._on_progress(i + 1, total_scans)
                
                if self._on_counts_update:
                    self._on_counts_update(max_counts, total_counts)
                
                if self._on_scan_complete:
                    self._on_scan_complete(result)
                
                # Update timing
                current_time = time.time()
                iteration_time = current_time - last_iteration_time
                last_iteration_time = current_time
                total_time += iteration_time
                
                # Estimate remaining time
                avg_time = total_time / (i + 1)
                remaining_scans = total_scans - (i + 1)
                remaining_time = remaining_scans * avg_time
                remaining_str = str(datetime.timedelta(seconds=int(remaining_time)))
                
                if self._on_time_update:
                    self._on_time_update(remaining_str)
            
            # All scans complete
            total_time_str = str(datetime.timedelta(seconds=int(total_time)))
            self._log(f"Scans finished. Total time: {total_time_str}")
            
            if self._on_all_complete:
                self._on_all_complete(output_folder)
                
        except Exception as e:
            self._log(f"Simulation error: {e}")
        finally:
            self._running = False
    
    def _generate_scan_folder_name(self, scan_point: List[float], 
                                    scan_mode: str,
                                    letter_encode_func: Callable) -> List[str]:
        """Generate folder name parts for a scan point."""
        parts = []
        
        if scan_mode == "momentum":
            parts.extend([
                f"qx_{letter_encode_func(scan_point[0])}",
                f"qy_{letter_encode_func(scan_point[1])}",
                f"qz_{letter_encode_func(scan_point[2])}",
                f"dE_{letter_encode_func(scan_point[3])}"
            ])
        elif scan_mode == "rlu":
            parts.extend([
                f"H_{letter_encode_func(scan_point[0])}",
                f"K_{letter_encode_func(scan_point[1])}",
                f"L_{letter_encode_func(scan_point[2])}",
                f"dE_{letter_encode_func(scan_point[3])}"
            ])
        else:  # Angle mode
            parts.extend([
                f"A1_{letter_encode_func(scan_point[0])}",
                f"A2_{letter_encode_func(scan_point[1])}",
                f"A3_{letter_encode_func(scan_point[2])}",
                f"A4_{letter_encode_func(scan_point[3])}"
            ])
        
        # Add crystal bending parameters
        if len(scan_point) > 4:
            parts.extend([
                f"rhm_{letter_encode_func(scan_point[4])}",
                f"rvm_{letter_encode_func(scan_point[5])}",
                f"rha_{letter_encode_func(scan_point[6])}",
                f"rva_{letter_encode_func(scan_point[7])}"
            ])
        
        return parts
    
    def wait_for_completion(self, timeout: float = None) -> bool:
        """
        Wait for the current simulation to complete.
        
        Args:
            timeout: Maximum time to wait in seconds, or None to wait indefinitely
            
        Returns:
            True if simulation completed, False if timed out
        """
        if self._simulation_thread is not None:
            self._simulation_thread.join(timeout)
            return not self._simulation_thread.is_alive()
        return True
