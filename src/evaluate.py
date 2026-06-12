"""評測:直接讀「評測集與知識盤點_v0.1.xlsx」的黃金問答集工作表。

兩段式評測(誠實標示範圍):
A. 檢索評測:recall@5、MRR——正確知識有沒有進 top-5。
B. 陷阱題硬規則評測:價格/injection 類陷阱題是否被 guards 層「確定性」攔截。
   攔不到的陷阱題(如「上機後改單」這類需要理解的)列為「需生成層評測」,
   接上真實 LLM 後以 Ragas 補齊(TODO)。

採計規則:狀態=已審核。
產出:reports/eval_<時間戳>.md;EVAL_MIN_RECALL 設定後低於門檻回非零碼(擋 CI)。

用法:
    python -m src.evaluate            # 讀 .env 的 EVAL_XLSX
    python -m src.evaluate path.xlsx  # 指定檔案
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .db import connect
from .guards import detect_injection, detect_price_intent
from .retrieve import search

SHEET = "黃金問答集"
TOP_K = 5


def _expected_ids(raw: str) -> list[str]:
    # 邊界:允許「K001、K002」或「K001,K002」多重引用
    return [t.strip() for t in str(raw).replace("、", ",").split(",") if t.strip()]


def run(xlsx: str) -> int:
    if not Path(xlsx).exists():
        raise SystemExit(f"找不到評測集:{xlsx}")
    df = pd.read_excel(xlsx, sheet_name=SHEET, dtype=str).fillna("")
    approved = df[df["狀態"] == "已審核"]
    scorable = approved[
        (approved["預期行為"] == "正確回答") & (~approved["應引用知識編號"].isin(["", "無"]))
    ]
    traps = approved[approved["預期行為"].isin(["正確拒答", "轉人工"])]

    if len(scorable) == 0 and len(traps) == 0:
        raise SystemExit("沒有已審核題目;先到黃金問答集出題並改狀態為「已審核」")

    # ---- A. 檢索評測 ----
    conn = connect()
    rows, hit_count, rr_sum = [], 0, 0.0
    for _, q in scorable.iterrows():
        expected = _expected_ids(q["應引用知識編號"])
        hits = search(conn, q["問題"], top_k=TOP_K)
        got = [h["doc_id"] for h in hits]
        rank = next((i + 1 for i, d in enumerate(got) if d in expected), None)
        hit_count += int(rank is not None)
        rr_sum += (1.0 / rank) if rank else 0.0
        rows.append((q["題號"], q["問題"], ",".join(expected), ",".join(got), "✓" if rank else "✗"))

    n = len(scorable)
    recall = (hit_count / n) if n else 0.0
    mrr = (rr_sum / n) if n else 0.0

    # ---- B. 陷阱題硬規則評測(不依賴 LLM,確定性) ----
    trap_rows, caught_count = [], 0
    for _, q in traps.iterrows():
        text = q["問題"]
        if detect_injection(text):
            caught, how = True, "injection 攔截"
        elif detect_price_intent(text):
            caught, how = True, "價格/交期意圖攔截"
        else:
            caught, how = False, "需生成層評測(TODO)"
        caught_count += int(caught)
        trap_rows.append((q["題號"], text, q["預期行為"], "✓ " + how if caught else "— " + how))

    mode = os.environ.get("EMBEDDING_MODE", "stub")
    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"eval_{datetime.now():%Y%m%d_%H%M%S}.md"
    lines = [
        "# 評測報告",
        "",
        f"- 時間:{datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 嵌入模式:{mode}" + ("(⚠ stub 假向量,檢索分數無選型意義)" if mode == "stub" else ""),
        "",
        "## A. 檢索評測(已審核事實題)",
        "",
        f"- 採計 {n} 題;**recall@{TOP_K} = {recall:.1%}**;**MRR = {mrr:.3f}**",
        "",
        "| 題號 | 問題 | 應引用 | 實際 top-5 doc | 命中 |",
        "|---|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rows],
        "",
        "## B. 陷阱題硬規則評測(已審核拒答/轉人工題)",
        "",
        f"- 採計 {len(traps)} 題;硬規則確定性攔截 **{caught_count}/{len(traps)}**;"
        f"其餘 {len(traps) - caught_count} 題需生成層評測(接 LLM 後以 Ragas 補)",
        "",
        "| 題號 | 問題 | 預期行為 | 硬規則結果 |",
        "|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} |" for a, b, c, d in trap_rows],
    ]
    out.write_text("\n".join(lines), encoding="utf-8")

    print(f"A 檢索:recall@{TOP_K}={recall:.1%} MRR={mrr:.3f} (n={n})")
    print(f"B 陷阱:硬規則攔截 {caught_count}/{len(traps)}")
    print(f"報告:{out}")

    min_recall = os.environ.get("EVAL_MIN_RECALL")
    if min_recall and recall < float(min_recall):
        print(f"低於門檻 EVAL_MIN_RECALL={min_recall},以非零碼結束(可擋 CI)")
        return 1
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "EVAL_XLSX", "../評測集與知識盤點_v0.1.xlsx"
    )
    raise SystemExit(run(target))
