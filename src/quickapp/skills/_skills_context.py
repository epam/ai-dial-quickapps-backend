from quickapp.skills._skill_source_context import SkillSourceContext


class _SkillsContext(SkillSourceContext):
    """Sink for the cross-source precedence diagnostics ``SkillsRegistry`` raises
    while merging.

    The registry is the only component that sees every source, so it is the only
    one that can report a shadowed skill — but it must not file that diagnostic
    into a *source* package's context, both because the coupling runs the wrong
    way and because a predefined-vs-``dial-skill`` collision does not belong in
    the DIAL *prompt* skills' context. Holds no skills of its own.
    """
