"""LightHermes 本地插件加载器"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Union


class PluginLoader:
    """安全加载本地工具插件"""

    def __init__(self, project_root: Union[str, Path] = ".", logger: Any = None):
        self.project_root = Path(project_root).resolve()
        self.logger = logger

    def load_tool_plugins(
        self,
        dispatcher: Any,
        config: Optional[Dict[str, Any]],
        strict: bool = False,
    ) -> List[str]:
        plugin_config = config or {}
        enabled = list(plugin_config.get("enabled") or [])
        if not enabled:
            return []

        dirs = list(plugin_config.get("dirs") or [])
        plugin_dirs = [self._resolve_plugin_dir(item) for item in dirs]

        loaded: List[str] = []
        for name in enabled:
            plugin_file = self._find_plugin_file(plugin_dirs, str(name))
            if plugin_file is None:
                continue

            try:
                module = self._import_plugin_module(str(name), plugin_file)
                self._register_module_tools(module, dispatcher)
                loaded.append(str(name))
            except Exception as exc:
                if strict:
                    raise
                if self.logger and hasattr(self.logger, "warning"):
                    self.logger.warning("Skip tool plugin %s: %s", name, exc)

        return loaded

    def _resolve_plugin_dir(self, relative_dir: str) -> Path:
        path = Path(relative_dir)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Plugin directory must stay inside project root")

        resolved = (self.project_root / path).resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError("Plugin directory must stay inside project root") from exc

        return resolved

    def _find_plugin_file(self, plugin_dirs: List[Path], plugin_name: str) -> Optional[Path]:
        for plugin_dir in plugin_dirs:
            candidate = plugin_dir / (plugin_name + ".py")
            if candidate.is_file():
                return candidate
        return None

    def _import_plugin_module(self, plugin_name: str, plugin_file: Path) -> ModuleType:
        module_name = "lighthermes_plugin_tool_" + plugin_name
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        if spec is None or spec.loader is None:
            raise ImportError("Cannot load plugin module: " + str(plugin_file))

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _register_module_tools(self, module: ModuleType, dispatcher: Any) -> None:
        register = getattr(module, "register", None)
        if callable(register):
            register(dispatcher)
            return

        tools = []
        for value in vars(module).values():
            if callable(value) and hasattr(value, "tool_info"):
                tools.append(value)

        if tools:
            dispatcher.register_tools(tools)
