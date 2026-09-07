"""创建当前 Harness 使用的完整白名单工具注册表。"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.harness.kubernetes import KubectlClient
from app.harness.registry import ToolDefinition, ToolRegistry
from app.harness.tools.company_search import CompanySearchArguments, company_search_handler
from app.harness.tools.kubernetes_read import EventsArguments, NamespaceArguments, PodLogsArguments, ResourceArguments, WorkloadArguments, read_handlers
from app.harness.tools.kubernetes_write import ApplyYamlArguments, RestartArguments, RollbackArguments, ScaleArguments, UpdateImageArguments, write_handlers
from app.services.search import SearchService


def build_tool_registry(session: Session, settings: Settings) -> ToolRegistry:
    registry, client = ToolRegistry(), KubectlClient(settings)
    registry.register(ToolDefinition("company_search", "检索公司内部资料和引用片段", CompanySearchArguments, True, company_search_handler(SearchService(session, settings))))
    reads = read_handlers(client)
    for name, description, model, handler in [
        ("k8s_list_namespaces", "列出所选集群 namespace", NamespaceArguments, reads[0]),
        ("k8s_get_workloads", "查询工作负载和 Pod 状态", WorkloadArguments, reads[1]),
        ("k8s_describe_resource", "读取资源详情和事件", ResourceArguments, reads[2]),
        ("k8s_get_pod_logs", "读取 Pod 最近日志", PodLogsArguments, reads[3]),
        ("k8s_get_events", "读取 namespace 事件", EventsArguments, reads[4]),
        ("k8s_get_rollout_status", "查询工作负载发布状态", ResourceArguments, reads[5]),
        ("k8s_get_resource_yaml", "读取资源 YAML（不支持 Secret）", ResourceArguments, reads[6]),
    ]: registry.register(ToolDefinition(name, description, model, True, handler))
    writes = write_handlers(client)
    for name, description, model, handler in [
        ("k8s_restart_deployment", "申请滚动重启 Deployment", RestartArguments, writes[0]),
        ("k8s_scale_workload", "申请调整工作负载副本数", ScaleArguments, writes[1]),
        ("k8s_rollback_deployment", "申请回滚 Deployment 上一版本", RollbackArguments, writes[2]),
        ("k8s_update_image", "申请更新容器镜像", UpdateImageArguments, writes[3]),
        ("k8s_apply_yaml", "申请完整部署白名单 YAML", ApplyYamlArguments, writes[4]),
    ]: registry.register(ToolDefinition(name, description, model, False, handler))
    return registry
