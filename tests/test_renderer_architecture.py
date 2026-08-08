from astrbot_plugin_latex_render_under_test.rendering import (
    capture,
    models,
    page_prepare,
    postprocess,
    renderer,
)


def test_renderer_keeps_compatibility_exports_for_split_phases() -> None:
    assert renderer.RenderOptions is models.RenderOptions
    assert renderer._prepare_page_for_capture is page_prepare._prepare_page_for_capture
    assert renderer._install_network_policy is page_prepare._install_network_policy
    assert renderer._group_pagination_blocks is capture._group_pagination_blocks
    assert renderer._calculate_page_slices is capture._calculate_page_slices
    assert renderer._add_page_number is postprocess._add_page_number
    assert renderer._enforce_image_budget is postprocess._enforce_image_budget
