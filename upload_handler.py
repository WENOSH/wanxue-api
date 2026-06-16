"""WanXue Upload Handler — 文件上传 + 文本提取"""
import os, logging

log = logging.getLogger("wanxue.upload")

ALLOWED_EXTENSIONS = {'.txt', '.md', '.pdf', '.docx'}

def extract_text_from_file(filepath: str) -> str:
    """从上传文件提取纯文本"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.txt' or ext == '.md':
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    elif ext == '.pdf':
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(filepath)
            text = '\n'.join([page.get_text() for page in doc])
            doc.close()
            return text
        except ImportError:
            log.warning("PyMuPDF not installed, trying pdfplumber")
            import pdfplumber
            with pdfplumber.open(filepath) as pdf:
                return '\n'.join([page.extract_text() or '' for page in pdf.pages])
    elif ext == '.docx':
        import docx
        doc = docx.Document(filepath)
        return '\n'.join([p.text for p in doc.paragraphs])
    else:
        raise ValueError(f"Unsupported format: {ext}")

def save_uploaded_file(uploaded_content: bytes, filename: str, upload_dir: str) -> str:
    """保存上传文件到本地，返回完整路径"""
    os.makedirs(upload_dir, exist_ok=True)
    # Sanitize filename
    safe_name = ''.join(c for c in filename if c.isalnum() or c in '._- ').strip()
    if not safe_name:
        safe_name = "uploaded_file"
    filepath = os.path.join(upload_dir, safe_name)
    with open(filepath, 'wb') as f:
        f.write(uploaded_content)
    return filepath
