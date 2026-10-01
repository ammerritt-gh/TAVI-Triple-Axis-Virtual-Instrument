category: fix
notice: Scripts that fit an orientation through TAVI's UB code, such as the TAS MCP server, now read a peak given with a positive 2θ and no scattering sense as sense +1, which turns the fitted orientation 180° about the vertical; give the sense explicitly to keep the old reading.

Calculate UB now gives the right crystal orientation on IN8, IN12 and PANDA, where it came out turned 180° and sent HKL moves after a fit to the wrong setting (PUMA was not affected). Saved peaks load unchanged and fit correctly, and a UB matrix saved before this fix loads as it was saved: on IN8, IN12 and PANDA the message center says it may still be turned and Calculate UB refits it.
