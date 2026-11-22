package glue.support;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * det 시나리오 값 도구: Gherkin에 적힌 JSON 리터럴을 읽고(parse), 실행 시점 기호를 풀고(resolve), 요청 본문 JSON을 쓴다(toJson).
 *
 * <p>기호 문법(설계 §3.2 닫힌 목록)은 문자열 값 전체가 아래 중 하나일 때만 기호로 본다.
 * <ul>
 *   <li>{@code today}, {@code today+N}, {@code today-N}: SUT 타임존의 오늘 ± N일, ISO 날짜. 타임존은 feature Background의
 *       {@code Given the SUT timezone is "<tz>"}(렌더러가 번들 harness.json에서 싣는다)로 받는다. 기본값은 없다:
 *       타임존 없이 {@code today} 기호를 풀면 IllegalStateException</li>
 *   <li>{@code ref:<var>}: 같은 시나리오의 선행 요청이 응답에서 담아 둔 변수 값. 없으면 IllegalStateException</li>
 *   <li>{@code uniq:<caseId>}: {@code "u" + sha1(caseId + salt) 앞 10자리}. 같은 케이스는 항상 같은 값(결정적)이고 서버는 generation마다 새로 뜬다.
 *       본 요청의 salt는 빈 문자열이고, 선행 요청은 {@code "#prior<k>"}(k는 0부터)다. 선행 요청과 본 요청이 같은 {@code uniq:} 값을
 *       들고 있어도 서로 다른 데이터를 만들게 하기 위해서다(하네스 계약: 만드는 데이터 값이 겹치지 않게)</li>
 * </ul>
 * JSON 처리는 외부 라이브러리 없이 이 클래스 안에서 한다(하네스 허용 의존성만 쓰기 위해서다).
 */
public final class DetValues {

    private static final Pattern TODAY = Pattern.compile("today(?:([+-])(\\d+))?");
    private static final String REF_PREFIX = "ref:";
    private static final String UNIQ_PREFIX = "uniq:";

    private DetValues() {
    }

    /** SUT 타임존 이름 → ZoneId. 비었거나 알 수 없는 이름이면 IllegalStateException(기본값으로 대신하지 않는다). */
    public static ZoneId zone(String name) {
        if (name == null || name.trim().isEmpty()) {
            throw new IllegalStateException("SUT 타임존이 정해지지 않았다(Background step 'the SUT timezone is' 필요)");
        }
        try {
            return ZoneId.of(name);
        } catch (java.time.DateTimeException bad) {
            throw new IllegalStateException("알 수 없는 SUT 타임존: " + name, bad);
        }
    }

    /** 본 요청용 기호 해석(uniq salt 없음). */
    public static Object resolve(Object value, Map<String, Object> vars, ZoneId sutZone) {
        return resolve(value, vars, "", sutZone);
    }

    /** 기호를 푼다. Map과 List는 안쪽 값까지 푼다. 기호가 아닌 값은 그대로 돌려준다. sutZone은 today 기호에만 쓴다(null이면 today에서 실패). */
    public static Object resolve(Object value, Map<String, Object> vars, String uniqSalt, ZoneId sutZone) {
        if (value instanceof Map) {
            Map<String, Object> resolved = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                resolved.put(String.valueOf(entry.getKey()), resolve(entry.getValue(), vars, uniqSalt, sutZone));
            }
            return resolved;
        }
        if (value instanceof List) {
            List<Object> resolved = new ArrayList<>();
            for (Object item : (List<?>) value) {
                resolved.add(resolve(item, vars, uniqSalt, sutZone));
            }
            return resolved;
        }
        if (!(value instanceof String)) {
            return value;
        }
        String text = (String) value;
        Matcher today = TODAY.matcher(text);
        if (today.matches()) {
            long offsetDays = today.group(1) == null ? 0 : Long.parseLong(today.group(2));
            if ("-".equals(today.group(1))) {
                offsetDays = -offsetDays;
            }
            if (sutZone == null) {
                throw new IllegalStateException("SUT 타임존 없이 날짜 기호를 풀 수 없다: " + text);
            }
            return LocalDate.now(sutZone).plusDays(offsetDays).toString();
        }
        if (text.startsWith(REF_PREFIX)) {
            String name = text.substring(REF_PREFIX.length());
            if (!vars.containsKey(name)) {
                throw new IllegalStateException("선행 요청이 담은 변수가 없다: " + name);
            }
            return vars.get(name);
        }
        if (text.startsWith(UNIQ_PREFIX)) {
            return uniq(text.substring(UNIQ_PREFIX.length()) + uniqSalt);
        }
        return text;
    }

    /** {@code uniq:<id>} 값. */
    public static String uniq(String id) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-1").digest(id.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder("u");
            for (int index = 0; hex.length() < 11; index++) {
                hex.append(String.format("%02x", digest[index]));
            }
            return hex.substring(0, 11);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    /** 쿼리·경로 변수로 보낼 문자열. 수는 지수 표기 없이 쓴다. */
    public static String text(Object value) {
        if (value instanceof BigDecimal) {
            return ((BigDecimal) value).toPlainString();
        }
        return String.valueOf(value);
    }

    // --- JSON 쓰기 ---------------------------------------------------------------------------------

    public static String toJson(Object value) {
        StringBuilder out = new StringBuilder();
        writeJson(value, out);
        return out.toString();
    }

    private static void writeJson(Object value, StringBuilder out) {
        if (value == null) {
            out.append("null");
        } else if (value instanceof String) {
            writeString((String) value, out);
        } else if (value instanceof BigDecimal) {
            out.append(((BigDecimal) value).toPlainString());
        } else if (value instanceof Number || value instanceof Boolean) {
            out.append(value);
        } else if (value instanceof Map) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                writeString(String.valueOf(entry.getKey()), out);
                out.append(':');
                writeJson(entry.getValue(), out);
            }
            out.append('}');
        } else if (value instanceof List) {
            out.append('[');
            boolean first = true;
            for (Object item : (List<?>) value) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                writeJson(item, out);
            }
            out.append(']');
        } else {
            writeString(String.valueOf(value), out);
        }
    }

    private static void writeString(String text, StringBuilder out) {
        out.append('"');
        for (int index = 0; index < text.length(); index++) {
            char ch = text.charAt(index);
            switch (ch) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (ch < 0x20) {
                        out.append(String.format("\\u%04x", (int) ch));
                    } else {
                        out.append(ch);
                    }
            }
        }
        out.append('"');
    }

    // --- JSON 읽기(RFC 8259 부분집합: 렌더러가 쓰는 리터럴 전부) ---------------------------------

    /** JSON 값 하나를 읽는다. 객체는 LinkedHashMap, 배열은 ArrayList, 수는 BigDecimal이다. 형식 오류는 IllegalArgumentException. */
    public static Object parse(String json) {
        Parser parser = new Parser(json);
        Object value = parser.value();
        parser.skipSpace();
        if (parser.position != json.length()) {
            throw parser.error("값 뒤에 남은 글자가 있다");
        }
        return value;
    }

    private static final class Parser {
        private final String text;
        private int position;

        Parser(String text) {
            this.text = text;
        }

        IllegalArgumentException error(String message) {
            return new IllegalArgumentException("JSON 리터럴 오류(" + position + "): " + message + ": " + text);
        }

        void skipSpace() {
            while (position < text.length() && Character.isWhitespace(text.charAt(position))) {
                position++;
            }
        }

        char peek() {
            if (position >= text.length()) {
                throw error("입력이 끝났다");
            }
            return text.charAt(position);
        }

        void expect(char wanted) {
            skipSpace();
            if (peek() != wanted) {
                throw error("'" + wanted + "'가 와야 한다");
            }
            position++;
        }

        Object value() {
            skipSpace();
            char ch = peek();
            if (ch == '{') {
                return object();
            }
            if (ch == '[') {
                return array();
            }
            if (ch == '"') {
                return string();
            }
            if (text.startsWith("null", position)) {
                position += 4;
                return null;
            }
            if (text.startsWith("true", position)) {
                position += 4;
                return Boolean.TRUE;
            }
            if (text.startsWith("false", position)) {
                position += 5;
                return Boolean.FALSE;
            }
            return number();
        }

        Map<String, Object> object() {
            Map<String, Object> result = new LinkedHashMap<>();
            expect('{');
            skipSpace();
            if (peek() == '}') {
                position++;
                return result;
            }
            while (true) {
                skipSpace();
                if (peek() != '"') {
                    throw error("객체 키는 문자열이어야 한다");
                }
                String key = string();
                expect(':');
                result.put(key, value());
                skipSpace();
                char next = peek();
                position++;
                if (next == '}') {
                    return result;
                }
                if (next != ',') {
                    throw error("',' 또는 '}'가 와야 한다");
                }
            }
        }

        List<Object> array() {
            List<Object> result = new ArrayList<>();
            expect('[');
            skipSpace();
            if (peek() == ']') {
                position++;
                return result;
            }
            while (true) {
                result.add(value());
                skipSpace();
                char next = peek();
                position++;
                if (next == ']') {
                    return result;
                }
                if (next != ',') {
                    throw error("',' 또는 ']'가 와야 한다");
                }
            }
        }

        String string() {
            expect('"');
            StringBuilder out = new StringBuilder();
            while (true) {
                char ch = peek();
                position++;
                if (ch == '"') {
                    return out.toString();
                }
                if (ch != '\\') {
                    out.append(ch);
                    continue;
                }
                char escape = peek();
                position++;
                switch (escape) {
                    case '"': out.append('"'); break;
                    case '\\': out.append('\\'); break;
                    case '/': out.append('/'); break;
                    case 'b': out.append('\b'); break;
                    case 'f': out.append('\f'); break;
                    case 'n': out.append('\n'); break;
                    case 'r': out.append('\r'); break;
                    case 't': out.append('\t'); break;
                    case 'u':
                        if (position + 4 > text.length()) {
                            throw error("\\u 뒤에 16진 4자리가 와야 한다");
                        }
                        try {
                            out.append((char) Integer.parseInt(text.substring(position, position + 4), 16));
                        } catch (NumberFormatException bad) {
                            throw error("\\u 뒤에 16진 4자리가 와야 한다");
                        }
                        position += 4;
                        break;
                    default:
                        throw error("알 수 없는 이스케이프 \\" + escape);
                }
            }
        }

        BigDecimal number() {
            int start = position;
            while (position < text.length() && "+-0123456789.eE".indexOf(text.charAt(position)) >= 0) {
                position++;
            }
            if (start == position) {
                throw error("값이 와야 한다");
            }
            try {
                return new BigDecimal(text.substring(start, position));
            } catch (NumberFormatException bad) {
                throw error("수 형식이 아니다");
            }
        }
    }
}
