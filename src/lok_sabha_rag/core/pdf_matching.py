"""Shared official RS PDF identity checks, independent of the retrieval backend."""
import html
import re
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import urlparse
def words(value):
    return ' '.join(re.findall(r'\w+',html.unescape(str(value or '')).casefold()))

def metadata_key(row,official=False):
    return (int(row.get('ses_no') if official else row.get('session_no')),
            int(row.get('qno') if official else row.get('ques_no')),
            str(row.get('qtype') if official else row.get('type')).strip().upper(),
            str(row.get('adate') if official else row.get('date'))[:10])

def safe_pdf(url,session):
    parsed=urlparse(str(url or ''))
    return (parsed.scheme=='https' and parsed.hostname=='sansad.in' and
            parsed.port in (None,443) and not parsed.username and not parsed.password and
            parsed.path.startswith(f'/getFile/annex/{session}/') and parsed.path.lower().endswith('.pdf'))

def safe_document(url,session):
    parsed=urlparse(str(url or ''))
    return (parsed.scheme=='https' and parsed.hostname=='sansad.in' and parsed.port in (None,443)
            and not parsed.username and not parsed.password
            and parsed.path.startswith(f'/getFile/annex/{session}/')
            and parsed.path.lower().endswith(('.pdf','.docx')))

def candidate(record,official):
    if metadata_key(record)!=metadata_key(official,True):return None
    # Same source record ID plus title, not merely a reused question number.
    if int(official.get('qslno') or 0)!=int(record['source_record_id']):return None
    if SequenceMatcher(None,words(record['subject']),words(official.get('qtitle'))).ratio()<.92:return None
    url=official.get('eng_file_dsp')
    if url and url.startswith('/') and not url.startswith('//'):url='https://sansad.in'+url
    else:url=official.get('files')
    return url if safe_document(url,record['session_no']) else None

def verify_text(text,record):
    prefix=text[:6000].replace('\u2013','-').replace('\u2014','-')
    # Official PDFs include joined words and the observed RAJAY spelling.
    if not re.search(r'\bRAJ(?:YA|AY)\s*SABHA\b',prefix,re.I):return False
    kind=record['type'].strip().upper()
    kind_pattern=r'UN[\s-]*STARRED' if kind=='UNSTARRED' else r'STARRED' if kind=='STARRED' else r'(?!)'
    number=int(record['ques_no'])
    number_pattern=r'\s*'.join(str(number))
    if not re.search(rf'\b{kind_pattern}\s+QUESTION\s*(?:NO\.?|NUMBER)?\s*[:.\-]?\s*\*?\s*{number_pattern}\b',prefix,re.I):return False
    date=datetime.strptime(record['date'],'%Y-%m-%d')
    anchor=re.search(r'(?:TO\s+BE\s+)?ANSWER(?:ED)?\s*ON\s*[:\-]?|FOR\s+ANSWER\s+ON',prefix,re.I)
    if not anchor:return False
    date_heading=prefix[anchor.end():anchor.end()+120]
    # A different numeric answer date must not be rescued by a date in the body.
    numeric=re.search(r'\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d(?:\s*\d){3})\b',date_heading)
    if numeric:
        return (int(numeric[1]),int(numeric[2]),int(re.sub(r'\s+','',numeric[3])))==(date.day,date.month,date.year)
    patterns=[rf'\b0?{date.day}[./-]0?{date.month}[./-]{date.year}\b',
              rf'\b0?{date.day}(?:st|nd|rd|th)?\s*,?\s*{date.strftime("%B")}\s*,?\s*{date.year}\b',
              rf'\b{date.strftime("%B")}\s+0?{date.day}(?:st|nd|rd|th)?\s*,?\s*{date.year}\b']
    return any(re.search(p,date_heading,re.I) for p in patterns)

def verify_bytes(data,url,record):
    import io
    from urllib.parse import urlparse
    if len(data)>12_000_000:raise ValueError('Document exceeds size limit')
    suffix=urlparse(url).path.lower()
    if suffix.endswith('.pdf'):
        if not data.startswith(b'%PDF-'):raise ValueError('Invalid PDF signature')
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(data))
        text='\n'.join(page.extract_text() or '' for page in reader.pages[:2])
        kind='pdf'
    elif suffix.endswith('.docx'):
        from zipfile import ZipFile
        import xml.etree.ElementTree as ET
        with ZipFile(io.BytesIO(data)) as archive:
            info=archive.getinfo('word/document.xml')
            if info.file_size>20_000_000:raise ValueError('Word XML exceeds size limit')
            root=ET.fromstring(archive.read(info))
        ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        text='\n'.join(''.join(t.text or '' for t in paragraph.iter(ns+'t')) for paragraph in root.iter(ns+'p'))
        kind='docx'
    else:raise ValueError('Unsupported original document type')
    return verify_text(text,record),kind
