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
