category: fix
notice: A blank, infinite or not-a-number bending radius that used to be silently accepted is now rejected when you enter or send it.

Entering or sending an invalid number, such as infinite or not-a-number, for a crystal's bending radius is refused with a clear error instead of being accepted and producing a broken simulation.
