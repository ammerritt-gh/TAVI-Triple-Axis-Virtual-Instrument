category: fix
notice: A module choice that is not one of the instrument's real options is now refused instead of silently building a different instrument.

Choosing an option for an instrument's optional module (such as a beam-focusing mirror) that is not one of the supported choices is now rejected instead of silently building an instrument that does not match what you asked for. Changing only some module options over the API no longer crashes the run.
