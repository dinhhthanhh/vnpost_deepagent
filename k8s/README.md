# ☸️ Hướng Dẫn Triển Khai VNPost Deep Agent Trên Kubernetes (K8s)

Tài liệu này hướng dẫn cách deploy hệ thống **VNPost Deep Agent Mipo** lên cụm Kubernetes môi trường Staging / Production.

---

## 1. Yêu Cầu Hạ Tầng (Prerequisites)
- Kubernetes Cluster 1.28+ (GKE, EKS, AKS hoặc On-premise k8s/RKE2).
- Ingress-NGINX Controller hỗ trợ SSE streaming (`proxy-buffering: "off"`).
- Cụm PostgreSQL HA (Cloud SQL, AWS RDS hoặc Zalando Postgres Operator) cho Checkpointer.
- Cụm Vector DB Qdrant.

---

## 2. Các Bước Triển Khai

### Bước 1: Tạo Namespace
```bash
kubectl create namespace vnpost-production
```

### Bước 2: Tạo Secret chứa Khóa Bảo Mật
Sao chép `k8s/base/secret.example.yaml` thành `secret.yaml` và điền thông tin:
```bash
kubectl apply -f k8s/base/secret.yaml
```

### Bước 3: Triển khai toàn bộ cụm qua Kustomize
```bash
kubectl apply -k k8s/base/
```

### Bước 4: Kiểm tra trạng thái triển khai
```bash
kubectl get pods -n vnpost-production -l app.kubernetes.io/name=vnpost-agent-core
kubectl get hpa -n vnpost-production
```

---

## 3. Kiến Trúc Vận Hành Trên K8s

| Thành phần | Cơ chế vận hành |
| :--- | :--- |
| **Stateless Pods** | Pods chạy Supervisor và 7 Subagents in-process, không lưu state trong đĩa cứng của Pod. |
| **PostgreSQL Checkpointer** | Mọi checkpoint của LangGraph và đơn nháp duyệt/hủy HITL được lưu vào PostgreSQL qua connection pool (`app/core/postgres.py`). |
| **Autoscaling HPA** | Tự động tăng từ 3 Pods lên tối đa 20 Pods khi CPU vượt quá 70%. |
| **Health Probes** | `livenessProbe` và `readinessProbe` trỏ vào `/healthz` đảm bảo zero-downtime rolling update. |
