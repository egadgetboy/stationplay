import symbols as S
from kit import Logo, svg


def logos():
    p = S.P()
    out = []
    for name, fn in S.SYMBOLS.items():
        out.append(
            Logo(
                name,
                name,
                "sym",
                lambda f=fn: svg(
                    '<rect width="512" height="512" fill="#3a4250"/>'
                    + S.centred(f(p), 256, 256, 460)
                ),
            )
        )
    return out
