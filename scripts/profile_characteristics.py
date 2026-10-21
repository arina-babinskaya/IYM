import argparse

from sqlalchemy import String, case, cast, func, select

from app.db import get_sessionmaker
from app.models import ProductCharacteristic as PC


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--grep", help="только характеристики, в названии которых есть эта строка")
    args = ap.parse_args()
    has_dims = case((PC.value_json.is_(None), 0), (cast(PC.value_json, String) == "null", 0), else_=1)
    with get_sessionmaker()() as s:
        stmt = select(PC.code, func.count(), func.count(PC.value_num), func.count(PC.unit), func.sum(has_dims))
        if args.grep:
            stmt = stmt.where(func.lower(PC.code).like(f"%{args.grep.lower()}%"))
        rows = s.execute(stmt.group_by(PC.code).order_by(func.count().desc()).limit(args.top)).all()
        print(f"{'характеристика':<30} {'товаров':>7} {'число':>6} {'ед.':>5} {'разм.':>5}  частые единицы | частые значения")
        for code, n, n_num, n_unit, n_dims in rows:
            units = s.execute(
                select(PC.unit, func.count()).where(PC.code == code, PC.unit.isnot(None))
                .group_by(PC.unit).order_by(func.count().desc()).limit(2)
            ).all()
            values = s.execute(
                select(PC.value_raw, func.count()).where(PC.code == code)
                .group_by(PC.value_raw).order_by(func.count().desc()).limit(3)
            ).all()
            unit_txt = ",".join(u for u, _ in units) or "-"
            values_txt = " | ".join(f"{(v or '')[:18]} ({c})" for v, c in values)
            print(f"{code[:30]:<30} {n:>7} {100 * n_num // n:>5}% {100 * n_unit // n:>4}% {100 * (n_dims or 0) // n:>4}%"
                  f"  {unit_txt} | {values_txt}")


if __name__ == "__main__":
    main()
