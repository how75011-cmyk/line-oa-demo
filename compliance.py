"""
Ad-copy compliance pre-check for LINE broadcasts (Taiwan food / cosmetics).

Flags wording that commonly triggers penalties before a broadcast goes out.
The word list is a demo sample, not an exhaustive or authoritative list, and
the result is a screening aid, not legal advice.
"""

from typing import Dict, List

DISCLAIMER = "此為用語初篩，不是法律意見；詞庫為示範樣本，實際判斷依商品類別與主管機關認定。"

RULES: List[Dict] = [
    {
        "category": "醫療效能",
        "words": ["治療", "治癒", "根治", "消炎", "抗癌", "防癌", "降血壓", "降血糖", "改善失眠"],
        "law": "食品安全衛生管理法第28條第2項／化粧品衛生安全管理法第10條第2項",
        "suggestion": "食品、化粧品不得宣稱醫療效能。改寫成成分、用法或使用感受的客觀描述。",
    },
    {
        "category": "誇大不實",
        "words": ["100%有效", "百分之百有效", "保證有效", "最有效", "第一品牌", "永久有效", "無副作用", "立即見效"],
        "law": "食品安全衛生管理法第28條第1項／化粧品衛生安全管理法第10條第1項／公平交易法第21條",
        "suggestion": "刪掉絕對化、保證性的用語，或附上可以查證的依據。",
    },
    {
        "category": "易生誤解（生理功能）",
        "words": ["增強免疫力", "減肥", "瘦身", "燃脂", "消脂", "排毒"],
        "law": "食品安全衛生管理法第28條第1項",
        "suggestion": "一般食品不宜宣稱生理功能，改寫成口味、份量或食用情境。",
    },
]


def _normalize(text: str) -> str:
    return "".join(text.split()).lower()


def check(text: str) -> List[Dict]:
    """Return one finding per matched word, in order of first appearance."""
    norm = _normalize(text)
    findings = []
    for rule in RULES:
        for word in rule["words"]:
            idx = norm.find(word.lower())
            if idx >= 0:
                findings.append(
                    {
                        "word": word,
                        "index": idx,
                        "category": rule["category"],
                        "law": rule["law"],
                        "suggestion": rule["suggestion"],
                    }
                )
    findings.sort(key=lambda f: f["index"])
    return findings
