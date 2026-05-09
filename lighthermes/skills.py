"""
LightHermes Markdown 技能加载与匹配边界
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class SkillLoader:
    """技能加载器 - 加载和匹配 Markdown 技能"""

    def __init__(self, skill_dirs: List[str]):
        self.skill_dirs = skill_dirs
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.load_all()

    def load_all(self):
        """加载所有技能"""
        for skill_dir in self.skill_dirs:
            if not os.path.exists(skill_dir):
                continue

            for file_path in Path(skill_dir).glob("*.md"):
                skill = self._parse_skill(file_path)
                if skill:
                    self.skills[skill["name"]] = skill

    def _parse_skill(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """解析技能文件"""
        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return None

            parts = content.split("---", 2)
            if len(parts) < 3:
                return None

            metadata = {}
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip()

            return {
                "name": metadata.get("name", file_path.stem),
                "description": metadata.get("description", ""),
                "type": metadata.get("type", "skill"),
                "category": metadata.get("category", "user"),
                "trigger": metadata.get("trigger", "auto"),
                "content": parts[2].strip(),
                "metadata": metadata
            }
        except Exception as e:
            print(f"Failed to parse skill {file_path}: {e}")
            return None

    def match_skill(self, query: str) -> Optional[Dict[str, Any]]:
        """匹配技能 - 简单的关键词匹配"""
        if query.startswith("/"):
            skill_name = query[1:]
            skill = self.skills.get(skill_name)
            if skill and skill.get("metadata", {}).get("type", "skill") == "skill":
                return skill
            return None

        query_lower = query.lower()
        query_words = set(query_lower.split())

        best_match = None
        best_score = 0

        for skill in self.skills.values():
            if skill.get("metadata", {}).get("type", "skill") != "skill":
                continue
            if skill["trigger"] != "auto":
                continue

            desc_lower = skill["description"].lower()
            content_lower = skill["content"].lower()

            desc_words = set(desc_lower.split())
            content_words = set(content_lower.split())

            score = len(query_words & desc_words) * 2 + len(query_words & content_words)

            if score > best_score:
                best_score = score
                best_match = skill

        return best_match if best_score > 2 else None

    def get_failure_reports(self) -> List[Dict[str, Any]]:
        """获取失败报告"""
        return [
            skill for skill in self.skills.values()
            if skill.get("metadata", {}).get("type") == "failure_report"
        ]

    def _tokenize_for_match(self, text: str) -> set:
        text = text.lower()
        tokens = set(text.split())
        tokens.update(char for char in text if '一' <= char <= '鿿')
        return {token for token in tokens if token.strip()}

    def _score_failure_report(self, report: Dict[str, Any], query_tokens: set, task_type: str) -> int:
        metadata = report.get("metadata", {})
        score = 0
        if metadata.get("task_type") == task_type:
            score += 4

        searchable = " ".join([
            report.get("name", ""),
            report.get("description", ""),
            report.get("content", "")
        ])
        report_tokens = self._tokenize_for_match(searchable)
        matches = len(query_tokens & report_tokens)
        score += matches

        if metadata.get("task_type") != task_type and matches < 2:
            return 0
        return score

    def recall_failure_reports(self, query: str, task_type: str, limit: int = 2) -> List[Dict[str, Any]]:
        """按任务类型和关键词召回失败报告"""
        query_tokens = self._tokenize_for_match(query)
        scored = []
        for report in self.get_failure_reports():
            score = self._score_failure_report(report, query_tokens, task_type)
            if score > 0:
                report = dict(report)
                report["score"] = score
                scored.append(report)

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def get_all_skills(self) -> List[Dict[str, Any]]:
        """获取所有技能"""
        return list(self.skills.values())
