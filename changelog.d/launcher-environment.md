category: fix
notice: If your simulations failed while the fast analytic engine still worked, this is the fix.

Starting TAVI now always uses the Python and McStas that belong to that installation. Where a machine carried a second installation under the same name, a normal start could take the program from one and the simulation engine from the other, and every neutron simulation then failed while the analytic engine carried on working. A separate repair tool fixes machines already installed with an earlier version, without reinstalling.
