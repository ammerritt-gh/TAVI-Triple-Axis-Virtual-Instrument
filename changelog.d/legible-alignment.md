category: minor
notice: Refine Lattice now refines only the parameters of your crystal system and refuses a set of peaks that cannot decide them, where it used to scale the whole lattice; add reflections or set the space group when it refuses.

After Calculate UB the UB Matrix dock shows how far each peak sits from your UB and whether each pair of peaks is at the angle its indices imply, so a mis-indexed peak is flagged, and Refine Lattice now respects the crystal system. The scattering-plane panel names the zone axis, the c* elevation and the a* azimuth, selecting a sample moves your UB onto its lattice, training grades reflections that lie in your mount's plane, and a locked plane runs at exactly its kappa from the GUI as from the API.
