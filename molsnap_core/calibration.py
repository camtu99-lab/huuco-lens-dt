"""Hiệu chuẩn độ tin cậy và từ chối kết luận (calibrated abstention), thuần Python.

CHỈ dùng với dữ liệu thật do nhóm gán nhãn. Mã này không chứa tham số nào đã huấn luyện sẵn: chưa có dữ liệu thì chưa có mô hình,
MolSnap vẫn dùng quy tắc minh bạch trong cvr.py và không hiển thị phần trăm.
"""
import math


def sigmoid(z):
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def fit_logistic(X, y, l2=1.0, lr=0.3, iters=3000):
    """Hồi quy logistic có điều chuẩn L2 (gradient descent). X: danh sách vector, y: 0/1. Trả về {"w": [...], "b": số}."""
    n, d = len(X), len(X[0])
    w, b = [0.0] * d, 0.0
    for _ in range(iters):
        gw, gb = [0.0] * d, 0.0
        for xi, yi in zip(X, y):
            p = sigmoid(sum(wj * xj for wj, xj in zip(w, xi)) + b)
            e = p - yi
            for j in range(d):
                gw[j] += e * xi[j]
            gb += e
        w = [wj - lr * (gw[j] / n + l2 * wj / n) for j, wj in enumerate(w)]
        b -= lr * gb / n
    return {"w": w, "b": b}


def predict_proba(model, x):
    return sigmoid(sum(w * v for w, v in zip(model["w"], x)) + model["b"])


def brier(probs, y):
    return sum((p - t) ** 2 for p, t in zip(probs, y)) / len(y)


def reliability(probs, y, bins=10):
    """Các thùng độ tin cậy: (cận dưới, cận trên, số mẫu, xác suất trung bình dự đoán, tần suất thực)."""
    out = []
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        idx = [i for i, p in enumerate(probs) if (lo <= p < hi) or (k == bins - 1 and p == 1.0)]
        if idx:
            out.append((lo, hi, len(idx), sum(probs[i] for i in idx) / len(idx), sum(y[i] for i in idx) / len(idx)))
    return out


def ece(probs, y, bins=10):
    """Expected Calibration Error."""
    n = len(y)
    return sum(c / n * abs(conf - acc) for _, _, c, conf, acc in reliability(probs, y, bins))


def isotonic_fit(scores, y):
    """Hồi quy đẳng hướng (PAV). Trả về danh sách (điểm, xác suất) tăng dần để nội suy bậc thang."""
    pts = sorted(zip(scores, y))
    blocks = [[s, t, 1] for s, t in pts]   # [tổng điểm... dùng trung bình], đơn giản: [điểm, trung bình nhãn, trọng số]
    out = []
    for s, t in pts:
        out.append([s, float(t), 1])
        while len(out) > 1 and out[-2][1] > out[-1][1]:
            a, b = out[-2], out[-1]
            w = a[2] + b[2]
            out[-2:] = [[b[0], (a[1] * a[2] + b[1] * b[2]) / w, w]]
    return [(o[0], o[1]) for o in out]


def isotonic_predict(model, s):
    for sc, p in model:
        if s <= sc:
            return p
    return model[-1][1]


def coverage_accuracy(conf, correct, thresholds):
    """Với mỗi ngưỡng τ: hệ thống chỉ trả lời khi conf >= τ. Trả về [(τ, độ phủ, độ chính xác trong phần được trả lời)]."""
    out = []
    for t in thresholds:
        ans = [c for cf, c in zip(conf, correct) if cf >= t]
        out.append((t, len(ans) / len(conf), (sum(ans) / len(ans)) if ans else None))
    return out


def choose_threshold(scores, is_positive, target_precision):
    """Ngưỡng nhỏ nhất để dự đoán 'dương' (ví dụ 'lỗi do học sinh') đạt độ chính xác (precision) mục tiêu trên tập hiệu chuẩn.
    Trả về None nếu không ngưỡng nào đạt: khi đó hệ thống phải từ chối kết luận chứ không được hạ mục tiêu."""
    cand = sorted(set(scores))
    for t in cand:
        sel = [p for s, p in zip(scores, is_positive) if s >= t]
        if sel and sum(sel) / len(sel) >= target_precision:
            return t
    return None
