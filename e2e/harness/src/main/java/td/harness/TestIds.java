package td.harness;

import io.restassured.path.json.JsonPath;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 결정적 testId. Python {@code td.testid.make}와 같은 규칙이고 같은 결과를 내야 한다(공유 표 tests/fixtures/testids.json).
 *
 * <p>{@code E2E_<arm>_<inputHash8>r<rep>[g<n>]_<featureSlug>#L<line>}. slug는 feature 단위로 정해진다.
 * 같은 slug의 feature가 둘 이상이면 호출자가 feature 상대 경로 순으로 {@link #make}를 부르고, 뒤에 오는 것에 {@code _2}, {@code _3}이 붙는다.
 */
public final class TestIds {

    static final List<String> ARMS = List.of("base", "jqa", "owl");
    static final int MAX_SLUG_LENGTH = 60;

    private static final Pattern WINDOWS_DRIVE = Pattern.compile("^[A-Za-z]:/.*");
    private static final Pattern HASH8 = Pattern.compile("[0-9a-f]{8}");
    private static final Pattern NON_ALNUM_RUN = Pattern.compile("[^A-Za-z0-9]+");
    private static final Pattern UNDERSCORE_RUN = Pattern.compile("_+");

    private TestIds() {
    }

    private static String relativePosix(String path) {
        String text = path.replace('\\', '/');
        if (text.startsWith("/") || WINDOWS_DRIVE.matcher(text).matches()) {
            throw new IllegalArgumentException("feature 경로는 generation 루트 기준 상대 경로여야 한다(절대 경로 금지): " + path);
        }
        return text;
    }

    private static String trimUnderscores(String text) {
        int start = 0;
        int end = text.length();
        while (start < end && text.charAt(start) == '_') {
            start++;
        }
        while (end > start && text.charAt(end - 1) == '_') {
            end--;
        }
        return text.substring(start, end);
    }

    private static String stem(String relative) {
        String fileName = relative.substring(relative.lastIndexOf('/') + 1);
        int dot = fileName.lastIndexOf('.');
        return dot > 0 ? fileName.substring(0, dot) : fileName;
    }

    /** feature 이름(없으면 파일 이름)에서 ASCII 영숫자와 {@code _}만 남긴 slug. 남는 글자가 없으면 상대 경로의 sha1 앞 8자리로 만든 {@code f<hash>}다. */
    public static String featureSlug(String path, String name) {
        String relative = relativePosix(path);
        String source = (name != null && !name.isEmpty()) ? name : stem(relative);
        String slug = UNDERSCORE_RUN.matcher(NON_ALNUM_RUN.matcher(source).replaceAll("_")).replaceAll("_");
        slug = trimUnderscores(slug);
        if (slug.length() > MAX_SLUG_LENGTH) {
            slug = slug.substring(0, MAX_SLUG_LENGTH);
        }
        slug = trimUnderscores(slug);
        if (slug.isEmpty()) {
            slug = "f" + sha1Prefix(relative);
        }
        return slug;
    }

    private static String sha1Prefix(String text) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-1").digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte item : digest) {
                hex.append(String.format("%02x", item));
            }
            return hex.substring(0, 8);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    /**
     * testId 하나. {@code slugs}(feature 경로 -> slug, 한 generation 동안 공유)가 있으면 feature가 slug를 소유하고 충돌 접미사가 붙는다.
     * {@code slugs}가 null이면 접미사가 없고 중복 testId는 IllegalArgumentException이다.
     */
    public static String make(String arm, String inputHash, int rep, Integer gen, String featurePath, int pickleLine,
            Set<String> taken, String name, Map<String, String> slugs) {
        if (!ARMS.contains(arm)) {
            throw new IllegalArgumentException("알 수 없는 arm: " + arm);
        }
        if (rep < 1 || rep > 9) {
            throw new IllegalArgumentException("rep는 1~9여야 한다: " + rep);
        }
        String hash8 = inputHash.length() > 8 ? inputHash.substring(0, 8) : inputHash;
        if (!HASH8.matcher(hash8).matches()) {
            throw new IllegalArgumentException("입력 해시가 16진수 8자리 이상이어야 한다: " + inputHash);
        }
        if (gen != null && gen < 1) {
            throw new IllegalArgumentException("gen은 1 이상이어야 한다: " + gen);
        }
        String prefix = "E2E_" + arm + "_" + hash8 + "r" + rep + (gen != null ? "g" + gen : "") + "_";
        String key = relativePosix(featurePath);
        String slug;
        if (slugs == null) {
            slug = featureSlug(key, name);
        } else if (slugs.containsKey(key)) {
            slug = slugs.get(key);
        } else {
            String base = featureSlug(key, name);
            Set<String> used = new HashSet<>(slugs.values());
            slug = base;
            int serial = 1;
            while (used.contains(slug)) {
                serial++;
                slug = base + "_" + serial;
            }
            slugs.put(key, slug);
        }
        String candidate = prefix + slug + "#L" + pickleLine;
        if (!taken.add(candidate)) {
            throw new IllegalArgumentException("중복 testId: " + candidate);
        }
        return candidate;
    }

    /** 한 scenario(pickle)의 testId와 표시 이름. */
    public record Entry(String testId, String featurePath, String featureName, int line, String scenarioName) {
    }

    /**
     * 한 generation의 testId 레지스트리. 입력은 S07이 dry-run 결과로 만든 {@code testids.json}이다.
     * <pre>
     * {"arm":"jqa","inputHash":"...","rep":1,"gen":null,
     *  "features":[{"path":"features/a.feature","name":"Owner search","pickles":[{"line":5,"name":"plain"}]}]}
     * </pre>
     * feature를 경로 순으로 정렬해 {@link #make}를 부르므로 Python 쪽과 같은 id가 나온다.
     */
    public static final class Registry {

        private final List<Entry> entries;
        private final Map<String, Entry> byPathAndLine = new HashMap<>();
        private final List<String> pathsLongestFirst;

        private Registry(List<Entry> entries) {
            this.entries = entries;
            Set<String> paths = new HashSet<>();
            for (Entry entry : entries) {
                byPathAndLine.put(entry.featurePath() + ":" + entry.line(), entry);
                paths.add(entry.featurePath());
            }
            pathsLongestFirst = new ArrayList<>(paths);
            pathsLongestFirst.sort(Comparator.comparingInt(String::length).reversed());
        }

        @SuppressWarnings("unchecked")
        public static Registry load(Path file) {
            JsonPath json = JsonPath.from(file.toFile());
            String arm = json.getString("arm");
            String inputHash = json.getString("inputHash");
            int rep = json.getInt("rep");
            Integer gen = json.get("gen");
            List<Map<String, Object>> features = new ArrayList<>(json.getList("features"));
            features.sort(Comparator.comparing(feature -> (String) feature.get("path")));
            Set<String> taken = new HashSet<>();
            Map<String, String> slugs = new HashMap<>();
            List<Entry> entries = new ArrayList<>();
            for (Map<String, Object> feature : features) {
                String path = (String) feature.get("path");
                String name = (String) feature.get("name");
                for (Map<String, Object> pickle : (List<Map<String, Object>>) feature.get("pickles")) {
                    int line = ((Number) pickle.get("line")).intValue();
                    entries.add(new Entry(make(arm, inputHash, rep, gen, path, line, taken, name, slugs), path,
                            name, line, (String) pickle.get("name")));
                }
            }
            return new Registry(entries);
        }

        public int size() {
            return entries.size();
        }

        /**
         * Cucumber가 주는 uri({@code classpath:features/a.feature}, {@code file:///.../features/a.feature})와 줄 번호로
         * 항목을 찾는다. 없으면 null이다.
         */
        public Entry lookup(String uri, int line) {
            String normalized = uri.replace('\\', '/');
            for (String path : pathsLongestFirst) {
                if (normalized.equals(path) || normalized.endsWith("/" + path) || normalized.endsWith(":" + path)) {
                    Entry entry = byPathAndLine.get(path + ":" + line);
                    if (entry != null) {
                        return entry;
                    }
                }
            }
            return null;
        }
    }
}
