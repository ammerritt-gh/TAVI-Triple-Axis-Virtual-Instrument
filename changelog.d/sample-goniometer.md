category: fix
notice: A saved session whose crystal orientation is not the default was simulated with the crystal turned the opposite way before this release, so peaks found in such a session may move.

Out-of-plane Q and HKL points are now reached the way a real sample stage reaches them: a turntable carrying two crossed arcs, with the arcs' travel enforced where a source documents it (PUMA and IN12 ±20°, PANDA ±15°; IN8 unlimited) and a refusal naming the arc, the angle it needs and its travel when a point is out of reach. The simulation no longer mounts the crystal with the inverse rotation: until now a crystal oriented 23° one way was simulated 23° the other way.
