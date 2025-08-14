import os
import json
import jieba
from collections import Counter

def tokenize(text):
    tokens = jieba.cut(text or '')
    return [
        t.strip() for t in tokens
        if len(t.strip()) > 1 and t.strip().isalnum()
    ]

def generate_wordcloud_json(records, output_path):
    total_counter = Counter()
    for (note,) in records:
        tokens = tokenize(note)
        total_counter.update(tokens)

    # 只保留前200项
    top_items = total_counter.most_common(200)
    items = [{'text': word, 'value': count} for word, count in top_items]
    
    tmp_path = str(output_path) + '.tmp'
    
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp_path, output_path)