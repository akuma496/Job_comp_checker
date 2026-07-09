import plotly.graph_objects as go

REQ_TYPE_COLORS = {
    "explicit": "#2E7D32",
    "context_inferred": "#EF6C00",
    "cooccurring": "#757575",
}
REQ_TYPE_LABELS = {
    "explicit": "Explicit",
    "context_inferred": "Context-Inferred",
    "cooccurring": "Co-occurring",
}
CATEGORY_LABELS = {
    "core_skill": "Core Skills",
    "tool": "Tools",
    "domain_knowledge": "Domain Knowledge",
    "seniority_leadership": "Seniority / Leadership",
}


def build_requirement_count_bar(counts: dict[str, int]) -> go.Figure:
    req_types = ["explicit", "context_inferred", "cooccurring"]
    fig = go.Figure(
        go.Bar(
            x=[REQ_TYPE_LABELS[t] for t in req_types],
            y=[counts.get(t, 0) for t in req_types],
            marker_color=[REQ_TYPE_COLORS[t] for t in req_types],
        )
    )
    fig.update_layout(
        height=280,
        margin=dict(l=10, r=10, t=20, b=10),
        yaxis_title="requirement count",
        showlegend=False,
    )
    return fig


def build_radar_figure(categories: list[str], job_values: list[float], resume_values: list[float]) -> go.Figure:
    """Both traces are pre-scaled by the caller onto the same 0-1-ish axis (job_values
    as the "ask", resume_values as how much of that ask is covered), so the resume
    polygon visibly falls inside the job polygon wherever coverage is weak."""
    labels = [CATEGORY_LABELS.get(c, c) for c in categories]
    # close the loop for a clean polygon
    labels_closed = labels + [labels[0]]
    job_closed = job_values + [job_values[0]]
    resume_closed = resume_values + [resume_values[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=job_closed,
            theta=labels_closed,
            name="Job Requirements",
            line=dict(color="#EF6C00", dash="dash"),
            fill="none",
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=resume_closed,
            theta=labels_closed,
            name="Resume Coverage",
            line=dict(color="#2E7D32"),
            fill="toself",
            opacity=0.6,
        )
    )
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, max(1.0, max(job_values, default=1))])),
        height=420,
        margin=dict(l=40, r=40, t=40, b=40),
        showlegend=True,
    )
    return fig


def build_heatmap_figure(row_labels: list[str], col_labels: list[str], z: list[list[float]]) -> go.Figure:
    col_display = [CATEGORY_LABELS.get(c, c) for c in col_labels]
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=col_display,
            y=row_labels,
            colorscale="RdYlGn",
            zmin=0,
            zmax=1,
            colorbar=dict(title="coverage"),
        )
    )
    fig.update_layout(
        height=max(300, 24 * len(row_labels) + 100),
        margin=dict(l=10, r=10, t=20, b=10),
    )
    return fig


def build_gap_bar_figure(labels: list[str], counts: list[int]) -> go.Figure:
    paired = sorted(zip(labels, counts), key=lambda p: p[1])
    sorted_labels = [p[0] for p in paired]
    sorted_counts = [p[1] for p in paired]
    fig = go.Figure(
        go.Bar(
            x=sorted_counts,
            y=sorted_labels,
            orientation="h",
            marker_color="#C62828",
        )
    )
    fig.update_layout(
        height=max(300, 24 * len(labels) + 100),
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="jobs missing this",
    )
    return fig
