import io
import json
import re
import urllib.request
from bs4 import BeautifulSoup
from app.config import Settings
from app.rag import KnowledgeBases
from app.providers import ProviderClients

def fetch_web_page(url: str, title: str) -> bytes:
    print(f"Fetching web page: {url}...")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as res:
        html = res.read().decode("utf-8", errors="ignore")
    
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
        tag.decompose()
    
    lines = [line.strip() for line in soup.get_text().splitlines() if line.strip()]
    content = f"# {title}\nNguồn: {url}\n\n" + "\n\n".join(lines)
    return content.encode("utf-8")

def fetch_google_drive_pdf(file_id: str) -> bytes:
    print(f"Fetching Google Drive PDF file ID: {file_id}...")
    url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download"
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()

def main():
    settings = Settings()
    providers = ProviderClients(settings)
    kb_factory = KnowledgeBases(settings, providers)
    kb = kb_factory.for_tenant("vnpost")
    
    targets = [
        ("vnpost_chuyen_phat_tieu_chuan.txt", "web", "https://vnpost.vn/vi/dich-vu/chuyen-phat-trong-nuoc/dich-vu-chuyen-phat-tieu-chuan-trong-nuoc", "DỊCH VỤ CHUYỂN PHÁT TIÊU CHUẨN TRONG NƯỚC"),
        ("vnpost_chuyen_phat_trong_nuoc.txt", "web", "https://vnpost.vn/vi/dich-vu/chuyen-phat-trong-nuoc", "DỊCH VỤ CHUYỂN PHÁT TRONG NƯỚC - VNPOST"),
        ("vnpost_ho_tro_khach_hang.txt", "web", "https://www.vnpost.vn/vi/ho-tro", "HỖ TRỢ KHÁCH HÀNG - HỎI ĐÁP VNPOST"),
        ("quy_trinh_tiep_nhan_khieu_nai.pdf", "gdrive", "1K1GN6Nkoh5N5QnU85dg8BtsYwbgBB0LO", "QUY TRÌNH TIẾP NHẬN VÀ GIẢI QUYẾT KHIẾU NẠI")
    ]
    
    for filename, type_, source, title in targets:
        print(f"\nProcessing {filename}...")
        try:
            if type_ == "web":
                raw = fetch_web_page(source, title)
            else:
                raw = fetch_google_drive_pdf(source)
            
            result = kb.ingest(filename, raw, is_global=True)
            print(f"Successfully ingested {filename}: {len(raw)} bytes, duplicate={result.get('duplicate', False)}")
        except Exception as e:
            print(f"Error ingesting {filename}: {e}")
            
    print("\n=== Current Knowledge Base Documents ===")
    for rec in kb.snapshot.records:
        print(f"- {rec['filename']} ({rec['bytes']} bytes)")
    print(f"Total chunks: {len(kb.snapshot.nodes)}, Revision: {kb.snapshot.revision}")

if __name__ == "__main__":
    main()
