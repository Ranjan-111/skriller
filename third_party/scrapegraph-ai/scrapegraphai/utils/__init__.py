"""Upstream exports loaded on demand to isolate optional dependency side effects."""
from importlib import import_module

_EXPORTS = {'extract_code': ('.cleanup_code', 'extract_code'),
 'cleanup_html': ('.cleanup_html', 'cleanup_html'),
 'reduce_html': ('.cleanup_html', 'reduce_html'),
 'execution_focused_analysis': ('.code_error_analysis', 'execution_focused_analysis'),
 'semantic_focused_analysis': ('.code_error_analysis', 'semantic_focused_analysis'),
 'syntax_focused_analysis': ('.code_error_analysis', 'syntax_focused_analysis'),
 'validation_focused_analysis': ('.code_error_analysis', 'validation_focused_analysis'),
 'execution_focused_code_generation': ('.code_error_correction',
                                       'execution_focused_code_generation'),
 'semantic_focused_code_generation': ('.code_error_correction',
                                      'semantic_focused_code_generation'),
 'syntax_focused_code_generation': ('.code_error_correction',
                                    'syntax_focused_code_generation'),
 'validation_focused_code_generation': ('.code_error_correction',
                                        'validation_focused_code_generation'),
 'convert_to_md': ('.convert_to_md', 'convert_to_md'),
 'export_to_csv': ('.data_export', 'export_to_csv'),
 'export_to_json': ('.data_export', 'export_to_json'),
 'export_to_xml': ('.data_export', 'export_to_xml'),
 'are_content_equal': ('.dict_content_compare', 'are_content_equal'),
 'CustomLLMCallbackManager': ('.llm_callback_manager', 'CustomLLMCallbackManager'),
 'get_logger': ('.logging', 'get_logger'),
 'get_verbosity': ('.logging', 'get_verbosity'),
 'set_formatting': ('.logging', 'set_formatting'),
 'set_handler': ('.logging', 'set_handler'),
 'set_propagation': ('.logging', 'set_propagation'),
 'set_verbosity': ('.logging', 'set_verbosity'),
 'set_verbosity_debug': ('.logging', 'set_verbosity_debug'),
 'set_verbosity_error': ('.logging', 'set_verbosity_error'),
 'set_verbosity_fatal': ('.logging', 'set_verbosity_fatal'),
 'set_verbosity_info': ('.logging', 'set_verbosity_info'),
 'set_verbosity_warning': ('.logging', 'set_verbosity_warning'),
 'setDEFAULT_HANDLER': ('.logging', 'setDEFAULT_HANDLER'),
 'unset_formatting': ('.logging', 'unset_formatting'),
 'unset_handler': ('.logging', 'unset_handler'),
 'unset_propagation': ('.logging', 'unset_propagation'),
 'unsetDEFAULT_HANDLER': ('.logging', 'unsetDEFAULT_HANDLER'),
 'warning_once': ('.logging', 'warning_once'),
 'prettify_exec_info': ('.prettify_exec_info', 'prettify_exec_info'),
 'Proxy': ('.proxy_rotation', 'Proxy'),
 'parse_or_search_proxy': ('.proxy_rotation', 'parse_or_search_proxy'),
 'search_proxy_servers': ('.proxy_rotation', 'search_proxy_servers'),
 'save_audio_from_bytes': ('.save_audio_from_bytes', 'save_audio_from_bytes'),
 'save_code_to_file': ('.save_code_to_file', 'save_code_to_file'),
 'transform_schema': ('.schema_trasform', 'transform_schema'),
 'crop_image': ('.screenshot_scraping.screenshot_preparation', 'crop_image'),
 'select_area_with_ipywidget': ('.screenshot_scraping.screenshot_preparation',
                                'select_area_with_ipywidget'),
 'select_area_with_opencv': ('.screenshot_scraping.screenshot_preparation',
                             'select_area_with_opencv'),
 'take_screenshot': ('.screenshot_scraping.screenshot_preparation', 'take_screenshot'),
 'detect_text': ('.screenshot_scraping.text_detection', 'detect_text'),
 'split_text_into_chunks': ('.split_text_into_chunks', 'split_text_into_chunks'),
 'dynamic_import': ('.sys_dynamic_import', 'dynamic_import'),
 'srcfile_import': ('.sys_dynamic_import', 'srcfile_import'),
 'num_tokens_calculus': ('.tokenizer', 'num_tokens_calculus')}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module, __name__), attribute)
    globals()[name] = value
    return value
