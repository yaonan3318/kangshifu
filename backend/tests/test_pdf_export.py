import pymupdf

from app.services.pdf_export import build_answer_pdf


def test_build_answer_pdf_returns_a_readable_pdf():
    content = build_answer_pdf(
        question="日报里有哪些气泡检测进展？",
        answer="根据内部资料，已完成模型训练与验证。[1]",
        sources=[{"citation_number": 1, "document_name": "日报汇总.txt", "location_text": "片段 1"}],
    )

    assert content.startswith(b"%PDF")
    assert len(content) > 500


def test_build_answer_pdf_paginates_long_answers():
    content = build_answer_pdf(
        question="长回答",
        answer="这是一段需要分页的中文回答。" * 1500,
        sources=[],
    )

    document = pymupdf.open(stream=content, filetype="pdf")
    assert document.page_count >= 2
    document.close()
