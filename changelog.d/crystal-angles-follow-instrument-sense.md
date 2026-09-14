category: fix
notice: IN8, IN12 and PANDA now start from their own default angles; a saved angle scan written from the old PUMA-shaped defaults should be re-checked.

Editing an energy or wavevector now moves the monochromator and analyser onto the branch the selected instrument actually uses, and a scan submitted through the API or started from fresh defaults on IN8, IN12 or PANDA is no longer refused or driven on the wrong side.
