"""Upstream exports loaded on demand to isolate optional dependency side effects."""
from importlib import import_module

_EXPORTS = {'BaseNode': ('.base_node', 'BaseNode'),
 'BatchGenerateAnswerNode': ('.batch_generate_answer_node', 'BatchGenerateAnswerNode'),
 'ConcatAnswersNode': ('.concat_answers_node', 'ConcatAnswersNode'),
 'ConditionalNode': ('.conditional_node', 'ConditionalNode'),
 'DescriptionNode': ('.description_node', 'DescriptionNode'),
 'FetchNode': ('.fetch_node', 'FetchNode'),
 'FetchNodeLevelK': ('.fetch_node_level_k', 'FetchNodeLevelK'),
 'FetchScreenNode': ('.fetch_screen_node', 'FetchScreenNode'),
 'GenerateAnswerCSVNode': ('.generate_answer_csv_node', 'GenerateAnswerCSVNode'),
 'GenerateAnswerFromImageNode': ('.generate_answer_from_image_node',
                                 'GenerateAnswerFromImageNode'),
 'GenerateAnswerNode': ('.generate_answer_node', 'GenerateAnswerNode'),
 'GenerateAnswerNodeKLevel': ('.generate_answer_node_k_level',
                              'GenerateAnswerNodeKLevel'),
 'GenerateAnswerOmniNode': ('.generate_answer_omni_node', 'GenerateAnswerOmniNode'),
 'GenerateCodeNode': ('.generate_code_node', 'GenerateCodeNode'),
 'GenerateScraperNode': ('.generate_scraper_node', 'GenerateScraperNode'),
 'GetProbableTagsNode': ('.get_probable_tags_node', 'GetProbableTagsNode'),
 'GraphIteratorNode': ('.graph_iterator_node', 'GraphIteratorNode'),
 'HtmlAnalyzerNode': ('.html_analyzer_node', 'HtmlAnalyzerNode'),
 'ImageToTextNode': ('.image_to_text_node', 'ImageToTextNode'),
 'MarkdownifyNode': ('.markdownify_node', 'MarkdownifyNode'),
 'MergeAnswersNode': ('.merge_answers_node', 'MergeAnswersNode'),
 'MergeGeneratedScriptsNode': ('.merge_generated_scripts_node',
                               'MergeGeneratedScriptsNode'),
 'ParseNode': ('.parse_node', 'ParseNode'),
 'ParseNodeDepthK': ('.parse_node_depth_k_node', 'ParseNodeDepthK'),
 'PromptRefinerNode': ('.prompt_refiner_node', 'PromptRefinerNode'),
 'RAGNode': ('.rag_node', 'RAGNode'),
 'ReasoningNode': ('.reasoning_node', 'ReasoningNode'),
 'RobotsNode': ('.robots_node', 'RobotsNode'),
 'SearchInternetNode': ('.search_internet_node', 'SearchInternetNode'),
 'SearchLinkNode': ('.search_link_node', 'SearchLinkNode'),
 'SearchLinksWithContext': ('.search_node_with_context', 'SearchLinksWithContext'),
 'TextToSpeechNode': ('.text_to_speech_node', 'TextToSpeechNode')}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module, __name__), attribute)
    globals()[name] = value
    return value
