"""
文案智能分段工具
按句子完整性分段，考虑口播时长和视频生成限制
"""
import os
import re
import json
from typing import List, Dict
from scripts.claude_client import ClaudeClient


def segment_by_sentences_ai(
    text: str,
    target_duration: int = 10,
    max_duration: int = 15,
    chars_per_second: float = 4.0,
    provider_id: str = None,
) -> List[Dict]:
    """
    使用 AI 智能分段（理解语义和情节）

    Args:
        text: 完整文案
        target_duration: 目标时长（秒），默认10秒
        max_duration: 最大时长（秒），默认15秒（seedance2.0限制）
        chars_per_second: 口播速度（字/秒），默认4字/秒
        provider_id: AI Provider ID

    Returns:
        分段结果列表

    分段策略：
    1. AI 理解文案的语义和情节结构
    2. 根据内容自然分段（如对比、列举、转折等）
    3. 保持句子完整性
    4. 控制每段时长在目标范围内
    """
    text = text.strip()
    if not text:
        return []

    target_chars = int(target_duration * chars_per_second)
    max_chars = int(max_duration * chars_per_second)

    prompt = f"""你是专业的视频脚本编辑。请将以下文案按照语义和情节结构智能分段。

# 文案内容
{text}

# 分段要求

1. **理解语义结构（最重要！）**
   - 识别对比结构（如"扔地上吃很快 vs 手喂吃很慢"必须在同一段）
   - 识别列举结构（如"食物分三档：最低档...中档...最高档"必须完整保留在同一段）
   - 识别因果关系（原因和结果尽量在同一段）
   - 识别场景转换（如"深夜"是新场景，应该独立成段）
   - **绝对不要在列举、对比、因果等逻辑结构中间切断**

2. **时长参考（非硬性限制）**
   - 目标时长：{target_duration}秒（约{target_chars}字）
   - 参考上限：{max_duration}秒（约{max_chars}字）
   - 口播速度：{chars_per_second}字/秒
   - **重要：为了保持语义完整，可以适当超过时长限制，系统会自动在合适的位置二次拆分**

3. **分段原则**
   - 优先保证语义完整性，其次考虑时长
   - 在自然的停顿点分段（句号、场景转换、话题转换）
   - 不要在句子中间、列举中间、对比中间切断

4. **输出格式**
   严格按照 JSON 格式输出，不要有任何其他文字。

   **关键要求：文案中的所有引号必须删除或替换为单引号，避免破坏 JSON 格式！**
   例如："那是"反正饿不死"的保底口粮" 应该改为 "那是'反正饿不死'的保底口粮"

```json
{{
  "segments": [
    {{"index": 1, "text": "第一段文案内容"}},
    {{"index": 2, "text": "第二段文案内容"}},
    ...
  ]
}}
```

要求：
- 只输出 JSON，不要任何解释
- 每段文案必须是原文的连续片段
- 所有段落拼接起来应该等于原文
- 段落之间不要有遗漏或重复
- **文案中的双引号必须全部替换为单引号**
"""

    try:
        from .ai_providers import apply_provider
        provider = apply_provider(provider_id or os.environ.get("AI_PROVIDER_SELECTED"))
        client = ClaudeClient(provider_id=provider.id)

        result = client.create_message(
            model=provider.model or os.getenv("ANTHROPIC_MODEL", client.model),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=int(os.getenv("SEGMENT_AI_MAX_TOKENS", "4000")),
            temperature=float(os.getenv("SEGMENT_AI_TEMPERATURE", "0.3")),
        )

        content = result.get("content") or []
        text_result = ""
        for item in content:
            if isinstance(item, dict) and item.get("type", "text") == "text":
                text_result += str(item.get("text") or "")

        if not text_result.strip():
            raise RuntimeError("AI 返回空内容")

        # 提取 JSON - 改进正则表达式以匹配多行
        json_match = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', text_result, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试查找第一个 { 到最后一个 } 之间的内容
            start = text_result.find('{')
            end = text_result.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = text_result[start:end+1]
            else:
                json_str = text_result.strip()

        # 调试：如果 JSON 为空，打印原始内容
        if not json_str.strip():
            print(f"⚠️ AI 返回内容无法提取 JSON，原始内容前 500 字符：\n{text_result[:500]}")
            raise RuntimeError("无法从 AI 返回中提取 JSON")

        # 尝试直接解析 JSON
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            # JSON 解析失败，尝试修复常见问题
            print(f"⚠️ JSON 解析失败，尝试修复：{e}")

            # 方法：手动提取 segments 数组
            try:
                # 尝试提取每个 segment 的 index 和 text
                segments_match = re.findall(
                    r'\{\s*"index"\s*:\s*(\d+)\s*,\s*"text"\s*:\s*"([^"]+(?:[^"\\]|\\.)*?)"\s*\}',
                    json_str,
                    re.DOTALL
                )

                if not segments_match:
                    # 如果上面的正则失败，尝试更宽松的匹配
                    # 逐行查找 "text": 后面的内容
                    lines = json_str.split('\n')
                    segments_data = []
                    current_index = 0

                    for line in lines:
                        index_match = re.search(r'"index"\s*:\s*(\d+)', line)
                        if index_match:
                            current_index = int(index_match.group(1))

                        text_match = re.search(r'"text"\s*:\s*"(.+)"', line)
                        if text_match and current_index > 0:
                            text_content = text_match.group(1)
                            # 移除可能的尾部逗号和引号
                            text_content = text_content.rstrip('",}')
                            segments_data.append({
                                "index": current_index,
                                "text": text_content
                            })
                            current_index = 0

                    if segments_data:
                        data = {"segments": segments_data}
                    else:
                        raise RuntimeError("无法提取 segments 数据")
                else:
                    # 使用正则匹配的结果
                    data = {
                        "segments": [
                            {"index": int(idx), "text": txt}
                            for idx, txt in segments_match
                        ]
                    }

                print(f"✓ 使用备用方法成功提取了 {len(data.get('segments', []))} 个段落")

            except Exception as fallback_error:
                print(f"⚠️ 备用解析也失败：{fallback_error}")
                print(f"JSON 内容（前 500 字符）：\n{json_str[:500]}")
                raise RuntimeError(f"JSON 解析失败: {e}")
        ai_segments = data.get("segments", [])

        if not ai_segments:
            raise RuntimeError("AI 返回的分段为空")

        # 转换为标准格式
        results = []
        current_time = 0.0

        for seg in ai_segments:
            segment_text = seg.get("text", "").strip()
            if not segment_text:
                continue

            char_count = _count_chars(segment_text)
            duration = char_count / chars_per_second

            # 如果 AI 分的段超过最大时长，智能拆分它
            if duration > max_duration:
                print(f"  ⚠️ 段落 {seg.get('index')} 超长 ({duration:.1f}秒)，智能拆分中...")
                sub_texts = _split_long_segment_smart(segment_text, int(max_chars))
                for sub_text in sub_texts:
                    sub_chars = _count_chars(sub_text)
                    sub_duration = sub_chars / chars_per_second
                    # 强制限制在15秒以内
                    sub_duration = min(sub_duration, max_duration)
                    results.append({
                        "index": len(results) + 1,
                        "text": sub_text,
                        "char_count": sub_chars,
                        "estimated_duration": round(sub_duration, 1),
                        "start_time": round(current_time, 1),
                        "end_time": round(current_time + sub_duration, 1),
                    })
                    current_time += sub_duration
                print(f"    ✓ 拆分为 {len(sub_texts)} 个子段落")
            else:
                # 强制限制在15秒以内
                duration = min(duration, max_duration)
                results.append({
                    "index": len(results) + 1,
                    "text": segment_text,
                    "char_count": char_count,
                    "estimated_duration": round(duration, 1),
                    "start_time": round(current_time, 1),
                    "end_time": round(current_time + duration, 1),
                })
                current_time += duration

        # 合并过短段落（<4秒），视频模型最少需要4秒
        results = _merge_short_segments(results, min_duration=4.0, chars_per_second=chars_per_second)

        return results

    except Exception as exc:
        print(f"⚠️ AI 分段失败，降级使用算法分段：{exc}")
        # 降级方案：使用算法分段
        return segment_by_sentences(text, target_duration, max_duration, chars_per_second)


def segment_by_sentences(
    text: str,
    target_duration: int = 10,
    max_duration: int = 15,
    chars_per_second: float = 4.0,
) -> List[Dict]:
    """
    按句子完整性智能分段

    Args:
        text: 完整文案
        target_duration: 目标时长（秒），默认10秒
        max_duration: 最大时长（秒），默认15秒（seedance2.0限制）
        chars_per_second: 口播速度（字/秒），默认4字/秒

    Returns:
        分段结果列表，每个元素包含：
        - index: 段落序号（从1开始）
        - text: 段落文案
        - char_count: 字数
        - estimated_duration: 预估时长（秒）
        - start_time: 开始时间（秒）
        - end_time: 结束时间（秒）

    分段策略：
    1. 优先在句子边界（。！？）切分
    2. 如果单句在10-15秒之间，保持完整
    3. 如果单句超过15秒，在逗号处切分
    4. 如果逗号片段仍超过15秒，强制按字数切分
    """
    text = text.strip()
    if not text:
        return []

    target_chars = int(target_duration * chars_per_second)
    max_chars = int(max_duration * chars_per_second)

    # 第一步：按句子切分（。！？）
    sentences = _split_into_sentences(text)

    # 第二步：合并短句，拆分长句
    segments = []
    current_segment = ""
    current_chars = 0

    for sentence in sentences:
        sentence_chars = _count_chars(sentence)

        # 如果当前句子本身就超过最大时长，需要拆分
        if sentence_chars > max_chars:
            # 先保存当前累积的内容
            if current_segment:
                segments.append(current_segment.strip())
                current_segment = ""
                current_chars = 0

            # 拆分超长句子
            sub_segments = _split_long_sentence(sentence, max_chars)
            segments.extend(sub_segments)
            continue

        # 如果加上这句话会超过目标时长
        if current_chars > 0 and current_chars + sentence_chars > target_chars:
            # 但如果加上后不超过最大时长，且当前累积很少，可以加上
            if current_chars + sentence_chars <= max_chars and current_chars < target_chars * 0.5:
                current_segment += sentence
                current_chars += sentence_chars
            else:
                # 保存当前段落，开始新段落
                segments.append(current_segment.strip())
                current_segment = sentence
                current_chars = sentence_chars
        else:
            # 继续累积
            current_segment += sentence
            current_chars += sentence_chars

    # 保存最后一个段落
    if current_segment:
        segments.append(current_segment.strip())

    # 第三步：生成结果
    results = []
    current_time = 0.0

    for index, segment_text in enumerate(segments, start=1):
        char_count = _count_chars(segment_text)
        duration = char_count / chars_per_second
        # 强制限制在15秒以内
        duration = min(duration, max_duration)

        results.append({
            "index": index,
            "text": segment_text,
            "char_count": char_count,
            "estimated_duration": round(duration, 1),
            "start_time": round(current_time, 1),
            "end_time": round(current_time + duration, 1),
        })

        current_time += duration

    # 合并过短段落（<4秒），视频模型最少需要4秒
    results = _merge_short_segments(results, min_duration=4.0, chars_per_second=chars_per_second)

    return results


def _merge_short_segments(results: List[Dict], min_duration: float = 4.0, chars_per_second: float = 4.0) -> List[Dict]:
    """
    合并过短段落，确保每段至少 min_duration 秒
    优先与前一段合并，如果是第一段则与后一段合并
    """
    if not results:
        return results

    merged = True
    while merged:
        merged = False
        new_results = []
        i = 0
        while i < len(results):
            seg = results[i]
            if seg["estimated_duration"] < min_duration and len(results) > 1:
                if i == 0:
                    # 第一段：与下一段合并
                    next_seg = results[i + 1]
                    combined_text = seg["text"] + next_seg["text"]
                    combined_chars = _count_chars(combined_text)
                    combined_duration = combined_chars / chars_per_second
                    new_results.append({
                        "index": len(new_results) + 1,
                        "text": combined_text,
                        "char_count": combined_chars,
                        "estimated_duration": round(combined_duration, 1),
                        "start_time": seg["start_time"],
                        "end_time": round(seg["start_time"] + combined_duration, 1),
                    })
                    i += 2
                else:
                    # 与前一段合并
                    prev_seg = new_results[-1]
                    combined_text = prev_seg["text"] + seg["text"]
                    combined_chars = _count_chars(combined_text)
                    combined_duration = combined_chars / chars_per_second
                    new_results[-1] = {
                        "index": prev_seg["index"],
                        "text": combined_text,
                        "char_count": combined_chars,
                        "estimated_duration": round(combined_duration, 1),
                        "start_time": prev_seg["start_time"],
                        "end_time": round(prev_seg["start_time"] + combined_duration, 1),
                    }
                    i += 1
                merged = True
            else:
                new_results.append(seg)
                i += 1
        results = new_results

    # 重新编号并修正时间戳
    current_time = 0.0
    for idx, seg in enumerate(results, start=1):
        seg["index"] = idx
        seg["start_time"] = round(current_time, 1)
        seg["end_time"] = round(current_time + seg["estimated_duration"], 1)
        current_time += seg["estimated_duration"]

    return results


def _split_into_sentences(text: str) -> List[str]:
    """
    按句子边界切分文本
    保留标点符号在句子末尾
    """
    # 按句子结束符切分，保留分隔符
    pattern = r'([^。！？!?]+[。！？!?]+)'
    sentences = re.findall(pattern, text)

    # 处理最后可能没有标点的部分
    matched_text = ''.join(sentences)
    remaining = text[len(matched_text):].strip()
    if remaining:
        sentences.append(remaining)

    return [s for s in sentences if s.strip()]


def _split_long_segment_smart(text: str, max_chars: int) -> List[str]:
    """
    智能拆分超长段落
    优先在句号、问号、感叹号等自然停顿点切分
    """
    # 如果不超长，直接返回
    if _count_chars(text) <= max_chars:
        return [text]

    # 第一步：尝试在句子边界切分（。！？）
    sentences = _split_into_sentences(text)

    segments = []
    current = ""
    current_chars = 0

    for sentence in sentences:
        sentence_chars = _count_chars(sentence)

        # 如果单句就超长，需要进一步拆分
        if sentence_chars > max_chars:
            # 先保存当前累积的内容
            if current:
                segments.append(current.strip())
                current = ""
                current_chars = 0

            # 在逗号、分号等次级停顿点拆分
            sub_parts = _split_long_sentence(sentence, max_chars)
            segments.extend(sub_parts)
            continue

        # 如果加上这句话会超长
        if current_chars > 0 and current_chars + sentence_chars > max_chars:
            # 保存当前段落
            segments.append(current.strip())
            current = sentence
            current_chars = sentence_chars
        else:
            # 继续累积
            current += sentence
            current_chars += sentence_chars

    # 保存最后一个段落
    if current:
        segments.append(current.strip())

    return [s for s in segments if s]


def _split_long_sentence(sentence: str, max_chars: int) -> List[str]:
    """
    拆分超长句子
    优先在逗号、分号、顿号处切分
    """
    # 先尝试在逗号、分号、顿号处切分
    parts = re.split(r'([，,、；;])', sentence)

    segments = []
    current = ""

    for part in parts:
        # 如果是分隔符，加到前一个片段
        if part in '，,、；;':
            current += part
            continue

        part_chars = _count_chars(part)
        current_chars = _count_chars(current)

        # 如果单个片段就超长，强制按字数切分
        if part_chars > max_chars:
            if current:
                segments.append(current.strip())
                current = ""

            # 强制按字数切分
            for chunk_idx in range(0, len(part), max_chars):
                chunk = part[chunk_idx:chunk_idx + max_chars]
                if chunk.strip():
                    segments.append(chunk.strip())
            continue

        # 如果加上会超长
        if current and current_chars + part_chars > max_chars:
            segments.append(current.strip())
            current = part
        else:
            current += part

    if current:
        segments.append(current.strip())

    return [s for s in segments if s]


def _count_chars(text: str) -> int:
    """
    计算有效字符数（去除空白）
    """
    return len(re.sub(r'\s+', '', text))


def format_segments_for_display(segments: List[Dict]) -> str:
    """
    格式化分段结果用于显示
    """
    if not segments:
        return "暂无分段结果"

    lines = ["# 分段结果\n"]
    total_duration = segments[-1]["end_time"] if segments else 0
    lines.append(f"**总时长：** {total_duration:.1f}秒 | **段落数：** {len(segments)}\n")

    for seg in segments:
        lines.append(f"## 段落 {seg['index']} ({seg['start_time']:.1f}s - {seg['end_time']:.1f}s)")
        lines.append(f"**时长：** {seg['estimated_duration']:.1f}秒 | **字数：** {seg['char_count']}字\n")
        lines.append(f"{seg['text']}\n")

    return "\n".join(lines)


def segments_to_table_data(segments: List[Dict]) -> List[List]:
    """
    转换为表格数据格式（用于 Gradio Dataframe）
    """
    if not segments:
        return []

    rows = []
    for seg in segments:
        rows.append([
            seg["index"],
            f"{seg['start_time']:.1f}s - {seg['end_time']:.1f}s",
            f"{seg['estimated_duration']:.1f}s",
            seg["char_count"],
            seg["text"][:50] + "..." if len(seg["text"]) > 50 else seg["text"]
        ])

    return rows


def validate_segments(segments: List[Dict], max_duration: int = 15) -> Dict:
    """
    验证分段结果

    Returns:
        {
            "valid": bool,
            "warnings": List[str],
            "stats": Dict
        }
    """
    if not segments:
        return {
            "valid": False,
            "warnings": ["没有分段结果"],
            "stats": {}
        }

    warnings = []

    # 检查是否有超长段落
    for seg in segments:
        if seg["estimated_duration"] > max_duration:
            warnings.append(
                f"段落 {seg['index']} 时长 {seg['estimated_duration']:.1f}秒 超过最大限制 {max_duration}秒"
            )

    # 检查是否有过短段落
    for seg in segments:
        if seg["estimated_duration"] < 4:
            warnings.append(
                f"段落 {seg['index']} 时长 {seg['estimated_duration']:.1f}秒 过短（视频模型最少需要4秒），建议合并"
            )

    total_duration = segments[-1]["end_time"] if segments else 0
    avg_duration = total_duration / len(segments) if segments else 0

    stats = {
        "total_segments": len(segments),
        "total_duration": round(total_duration, 1),
        "avg_duration": round(avg_duration, 1),
        "min_duration": round(min(s["estimated_duration"] for s in segments), 1),
        "max_duration": round(max(s["estimated_duration"] for s in segments), 1),
    }

    return {
        "valid": len(warnings) == 0,
        "warnings": warnings,
        "stats": stats
    }
