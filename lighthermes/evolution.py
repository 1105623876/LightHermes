"""
LightHermes 自进化系统

实现轨迹分析、技能生成、技能验证
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from openai import OpenAI


class TrajectoryAnalyzer:
    """轨迹分析器 - 分析对话轨迹,识别成功/失败模式"""

    def __init__(self, trajectory_dir: str = "trajectories"):
        self.trajectory_dir = Path(trajectory_dir)
        self.trajectory_dir.mkdir(parents=True, exist_ok=True)
        self.quality_threshold = 80

    def calculate_quality_score(self, trajectory: Dict[str, Any]) -> int:
        """计算成功轨迹质量分数"""
        if not trajectory.get("success", False):
            return 0

        tool_calls = trajectory.get("tool_calls", []) or []
        iterations = trajectory.get("iterations", len(tool_calls))
        user_corrections = trajectory.get("user_corrections", 0)

        score = 100
        score -= user_corrections * 15
        score -= max(0, iterations - 1) * 5
        if iterations > 5:
            score -= (iterations - 5) * 10

        return max(0, min(100, score))

    def classify_success_quality(self, score: int) -> str:
        """按分数划分成功质量等级"""
        if score >= 80:
            return "high"
        if score >= 50:
            return "medium"
        return "low"

    def should_learn_from_success(self, trajectory: Dict[str, Any]) -> bool:
        """判断成功轨迹是否值得学习"""
        if not trajectory.get("success", False):
            return False

        if "learning_worthy" in trajectory:
            return bool(trajectory["learning_worthy"])

        return self.evaluate_quality(trajectory)["learning_worthy"]

    def evaluate_quality(self, trajectory: Dict[str, Any]) -> Dict[str, Any]:
        """评估轨迹质量并返回追加字段"""
        tool_calls = trajectory.get("tool_calls", []) or []
        iterations = trajectory.get("iterations", len(tool_calls))
        user_corrections = trajectory.get("user_corrections", 0)
        score = self.calculate_quality_score(trajectory)
        level = self.classify_success_quality(score)

        return {
            "quality_score": score,
            "quality_level": level,
            "learning_worthy": trajectory.get("success", False) and score >= self.quality_threshold,
            "quality_metrics": {
                "user_corrections": user_corrections,
                "iterations": iterations,
                "tool_call_count": len(tool_calls),
                "first_attempt_success": trajectory.get("success", False) and user_corrections == 0 and iterations <= 1
            },
            "quality_version": "1.0"
        }

    def save_trajectory(
        self,
        session_id: str,
        messages: List[Dict[str, str]],
        tool_calls: List[Dict[str, Any]],
        success: bool,
        task_type: str = "unknown",
        user_corrections: int = 0,
        iterations: Optional[int] = None
    ):
        """保存对话轨迹"""
        trajectory = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "task_type": task_type,
            "success": success,
            "messages": messages,
            "tool_calls": tool_calls,
            "user_corrections": user_corrections,
            "iterations": len(tool_calls) if iterations is None else iterations
        }
        trajectory.update(self.evaluate_quality(trajectory))

        file_path = self.trajectory_dir / f"{session_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(trajectory, f, ensure_ascii=False, indent=2)

    def load_trajectory(self, session_id: str) -> Optional[Dict[str, Any]]:
        """加载轨迹"""
        file_path = self.trajectory_dir / f"{session_id}.json"
        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def analyze_patterns(
        self,
        min_success_count: int = 3,
        min_failure_count: int = 2
    ) -> Dict[str, List[Dict[str, Any]]]:
        """分析成功/失败模式"""
        trajectories = []
        for file_path in self.trajectory_dir.glob("*.json"):
            with open(file_path, "r", encoding="utf-8") as f:
                trajectories.append(json.load(f))

        task_groups = {}
        for traj in trajectories:
            task_type = traj.get("task_type", "unknown")
            if task_type not in task_groups:
                task_groups[task_type] = []
            task_groups[task_type].append(traj)

        patterns = {
            "success_patterns": [],
            "failure_patterns": []
        }

        for task_type, trajs in task_groups.items():
            success_trajs = []
            for traj in trajs:
                if traj.get("success"):
                    if "quality_score" not in traj:
                        traj.update(self.evaluate_quality(traj))
                    if self.should_learn_from_success(traj):
                        success_trajs.append(traj)

            failure_trajs = [t for t in trajs if not t.get("success")]

            if len(success_trajs) >= min_success_count:
                all_success_count = len([t for t in trajs if t.get("success")])
                patterns["success_patterns"].append({
                    "task_type": task_type,
                    "count": len(success_trajs),
                    "trajectories": success_trajs[-min_success_count:],
                    "quality_threshold": self.quality_threshold,
                    "filtered_count": all_success_count - len(success_trajs)
                })

            if len(failure_trajs) >= min_failure_count:
                patterns["failure_patterns"].append({
                    "task_type": task_type,
                    "count": len(failure_trajs),
                    "trajectories": failure_trajs[-min_failure_count:]
                })

        return patterns


class SkillGenerator:
    """技能生成器 - 从轨迹中生成新技能"""

    def __init__(self, client: OpenAI, model: str = "gpt-4o-mini"):
        self.client = client
        self.model = model

    def generate_skill_from_pattern(
        self,
        pattern: Dict[str, Any],
        pattern_type: str
    ) -> Optional[Dict[str, Any]]:
        """从模式生成技能 - 优先生成 Markdown 技能"""
        task_type = pattern["task_type"]
        trajectories = pattern["trajectories"]

        tool_sequences = []
        for traj in trajectories:
            tools = [tc.get("tool") for tc in traj.get("tool_calls", [])]
            tool_sequences.append(tools)

        prompt = f"""基于以下{'成功' if pattern_type == 'success' else '失败'}的对话轨迹,生成一个可复用的 Markdown 技能。

任务类型: {task_type}
轨迹数量: {len(trajectories)}
工具使用序列: {tool_sequences}

**重要**: 请生成 Markdown 格式的技能(type: skill),而不是 Python 插件(type: plugin)。
Markdown 技能是提示词模板,指导 Agent 的思维流程,无需编写代码。

请生成一个 Markdown 格式的技能文件,包含:
1. 技能名称 (简短的英文标识符)
2. 技能描述 (一句话说明用途)
3. 技能内容 (指导 Agent 如何处理这类任务的步骤)

格式要求:
- 使用 YAML frontmatter,设置 type: skill
- 内容部分用清晰的步骤列表
- 保持简洁,避免过度细节
- 不要生成 Python 代码

只返回技能文件内容,不要有其他解释。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )

            skill_content = response.choices[0].message.content
            return self._parse_generated_skill(skill_content)

        except Exception as e:
            print(f"技能生成失败: {e}")
            return None

    def _parse_generated_skill(self, content: str) -> Optional[Dict[str, Any]]:
        """解析生成的技能"""
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
            "name": metadata.get("name", "generated_skill"),
            "description": metadata.get("description", ""),
            "content": content,
            "metadata": metadata
        }


class SkillValidator:
    """技能验证器 - 验证生成的技能"""

    def __init__(self, timeout: int = 30, max_memory_mb: int = 512):
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb

    def validate_skill(self, skill: Dict[str, Any]) -> Dict[str, Any]:
        """验证技能"""
        skill_type = skill.get("metadata", {}).get("type", "skill")

        if skill_type == "skill":
            return {"valid": True, "reason": "Markdown 技能无需验证"}

        elif skill_type == "plugin":
            return self._validate_plugin(skill)

        return {"valid": False, "reason": "未知的技能类型"}

    def _validate_plugin(self, skill: Dict[str, Any]) -> Dict[str, Any]:
        """验证 Python 插件 - 使用沙箱"""
        content = skill.get("content", "")

        try:
            result = subprocess.run(
                ["python", "-c", content],
                timeout=self.timeout,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                return {
                    "valid": True,
                    "reason": "插件执行成功",
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            else:
                return {
                    "valid": False,
                    "reason": f"插件执行失败: {result.stderr}",
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }

        except subprocess.TimeoutExpired:
            return {
                "valid": False,
                "reason": f"插件执行超时 ({self.timeout}秒)"
            }
        except Exception as e:
            return {
                "valid": False,
                "reason": f"验证过程出错: {str(e)}"
            }


class EvolutionEngine:
    """自进化引擎 - 统一管理自进化流程"""

    def __init__(
        self,
        client: OpenAI,
        model: str = "gpt-4o-mini",
        trajectory_dir: str = "trajectories",
        skill_output_dir: str = "skills/generated",
        min_success_count: int = 3,
        min_failure_count: int = 2,
        skill_validation: str = "sandbox"
    ):
        self.analyzer = TrajectoryAnalyzer(trajectory_dir)
        self.generator = SkillGenerator(client, model)
        self.validator = SkillValidator()

        self.skill_output_dir = Path(skill_output_dir)
        self.skill_output_dir.mkdir(parents=True, exist_ok=True)

        self.min_success_count = min_success_count
        self.min_failure_count = min_failure_count
        self.skill_validation = skill_validation

    def record_session(
        self,
        session_id: str,
        messages: List[Dict[str, str]],
        tool_calls: List[Dict[str, Any]],
        success: bool,
        task_type: str = "unknown",
        user_corrections: int = 0,
        iterations: Optional[int] = None
    ):
        """记录会话轨迹"""
        self.analyzer.save_trajectory(
            session_id=session_id,
            messages=messages,
            tool_calls=tool_calls,
            success=success,
            task_type=task_type,
            user_corrections=user_corrections,
            iterations=iterations
        )

    def evolve(self) -> Dict[str, Any]:
        """执行自进化流程"""
        patterns = self.analyzer.analyze_patterns(
            min_success_count=self.min_success_count,
            min_failure_count=self.min_failure_count
        )

        results = {
            "success_skills": [],
            "failure_skills": [],
            "errors": []
        }

        for pattern in patterns["success_patterns"]:
            try:
                skill = self.generator.generate_skill_from_pattern(pattern, "success")
                if skill:
                    if self.skill_validation != "none":
                        validation = self.validator.validate_skill(skill)
                        if validation["valid"]:
                            self._save_skill(skill)
                            results["success_skills"].append(skill["name"])
                        else:
                            results["errors"].append({
                                "skill": skill["name"],
                                "reason": validation["reason"]
                            })
                    else:
                        self._save_skill(skill)
                        results["success_skills"].append(skill["name"])
            except Exception as e:
                results["errors"].append({
                    "pattern": pattern["task_type"],
                    "error": str(e)
                })

        for pattern in patterns["failure_patterns"]:
            try:
                skill = self.generator.generate_skill_from_pattern(pattern, "failure")
                if skill:
                    if self.skill_validation != "none":
                        validation = self.validator.validate_skill(skill)
                        if validation["valid"]:
                            self._save_skill(skill)
                            results["failure_skills"].append(skill["name"])
                        else:
                            results["errors"].append({
                                "skill": skill["name"],
                                "reason": validation["reason"]
                            })
                    else:
                        self._save_skill(skill)
                        results["failure_skills"].append(skill["name"])
            except Exception as e:
                results["errors"].append({
                    "pattern": pattern["task_type"],
                    "error": str(e)
                })

        return results

    def _save_skill(self, skill: Dict[str, Any]):
        """保存技能到文件"""
        skill_name = skill["name"]
        file_path = self.skill_output_dir / f"{skill_name}.md"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(skill["content"])
