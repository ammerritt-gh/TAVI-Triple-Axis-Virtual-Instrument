category: fix
notice: A saved session whose crystal orientation (UB) is not the default now simulates the crystal where the UB puts it; before this release the simulation turned it the opposite way, so peaks found in such a session may move.

Out-of-plane Q and HKL points are now reached the way a real sample stage reaches them: a turntable carrying two crossed arcs, with the arcs' travel enforced where a source documents it (IN12 ±20°, PANDA ±15°; PUMA and IN8 unlimited) and a refusal naming the arc, the angle it needs and its travel when a point is out of reach. The simulated crystal now sits exactly where the UB matrix puts it: until now the simulation mounted it with the inverse rotation, so a crystal oriented 23° one way was simulated 23° the other way.
