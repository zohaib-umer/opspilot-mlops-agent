from datetime import datetime, timezone

from kubernetes import client, config


class KubernetesTools:
    def __init__(self, settings, core=None, apps=None):
        self.settings = settings
        self.core, self.apps = core, apps

    def connect(self, args):
        if args.namespace != self.settings.kube_namespace:
            raise PermissionError("Namespace is not approved")
        if self.core is None:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            self.core, self.apps = client.CoreV1Api(), client.AppsV1Api()
        return {"namespace": args.namespace, "_request_timeout": self.settings.tool_timeout}

    def pods(self, args):
        opts = self.connect(args)
        pods = self.core.list_namespaced_pod(label_selector="app=prediction-api", **opts)
        records = []
        for p in pods.items:
            containers = p.status.container_statuses or []
            records.append({"name": p.metadata.name, "phase": p.status.phase,
                            "ready": bool(containers) and all(c.ready for c in containers),
                            "restarts": sum(c.restart_count for c in containers),
                            "conditions": [c.to_dict() for c in (p.status.conditions or [])],
                            "containers": [c.to_dict() for c in containers]})
        return {"pods": records}

    def deployments(self, args):
        opts = self.connect(args)
        items = self.apps.list_namespaced_deployment(label_selector="app=prediction-api", **opts)
        return {"deployments": [{"name": d.metadata.name, "desired": d.spec.replicas,
                                 "ready": d.status.ready_replicas or 0,
                                 "updated": d.status.updated_replicas or 0,
                                 "generation": d.metadata.generation,
                                 "observed_generation": d.status.observed_generation,
                                 "images": [c.image for c in d.spec.template.spec.containers],
                                 "annotations": d.spec.template.metadata.annotations or {}}
                                for d in items.items]}

    def services(self, args):
        opts = self.connect(args)
        services = self.core.list_namespaced_service(label_selector="app=prediction-api", **opts)
        return {"services": [{"name": s.metadata.name, "type": s.spec.type,
                               "cluster_ip": s.spec.cluster_ip, "selector": s.spec.selector,
                               "ports": [p.to_dict() for p in s.spec.ports]} for s in services.items]}

    def events(self, args):
        opts = self.connect(args)
        events = self.core.list_namespaced_event(**opts)
        return {"events": [{"reason": e.reason, "message": e.message,
                             "object": e.involved_object.name, "count": e.count}
                            for e in events.items][-50:]}

    def logs(self, args):
        opts = self.connect(args)
        if not args.pod:
            raise ValueError("pod is required")
        return {"pod": args.pod, "logs": self.core.read_namespaced_pod_log(
            args.pod, tail_lines=100, limit_bytes=12000, **opts)}

    def restart(self, args):
        opts = self.connect(args)
        self.apps.patch_namespaced_deployment(
            self.settings.kube_deployment,
            {"spec": {"template": {"metadata": {"annotations": {
                "opspilot/restarted-at": datetime.now(timezone.utc).isoformat(),
            }}}}}, **opts,
        )
        return {"requested": "rollout restart", "deployment": self.settings.kube_deployment,
                "namespace": args.namespace}
