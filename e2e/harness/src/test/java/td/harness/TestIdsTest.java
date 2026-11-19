package td.harness;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.restassured.path.json.JsonPath;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

/** Python td.testid.make와 같은 id를 만드는지 공유 표(tests/fixtures/testids.json)로 검증한다(REQ-027). */
class TestIdsTest {

    private static final String TABLE_PROPERTY = "td.fixtures.testids";

    private static JsonPath table() {
        String path = System.getProperty(TABLE_PROPERTY);
        assertThat(path).as("시스템 속성 " + TABLE_PROPERTY).isNotBlank();
        return JsonPath.from(new File(path));
    }

    static Stream<Map<String, Object>> cases() {
        List<Map<String, Object>> cases = table().getList("cases");
        return cases.stream();
    }

    static Stream<Map<String, Object>> errors() {
        List<Map<String, Object>> errors = table().getList("errors");
        return errors.stream();
    }

    @SuppressWarnings("unchecked")
    @ParameterizedTest(name = "{0}")
    @MethodSource("cases")
    void sharedTableMatchesPython(Map<String, Object> testCase) {
        Integer gen = (Integer) testCase.get("gen");
        List<Map<String, Object>> features = new java.util.ArrayList<>((List<Map<String, Object>>) testCase.get("features"));
        features.sort(Comparator.comparing(feature -> (String) feature.get("path")));
        Set<String> taken = new HashSet<>();
        Map<String, String> slugs = new HashMap<>();
        List<String> made = new java.util.ArrayList<>();
        for (Map<String, Object> feature : features) {
            for (Object line : (List<Object>) feature.get("pickles")) {
                made.add(TestIds.make((String) testCase.get("arm"), (String) testCase.get("inputHash"),
                        (Integer) testCase.get("rep"), gen, (String) feature.get("path"), ((Number) line).intValue(),
                        taken, (String) feature.get("name"), slugs));
            }
        }
        assertThat(made).isEqualTo(testCase.get("expected"));
        assertThat(new HashSet<>(made)).hasSameSizeAs(made);
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("errors")
    void sharedTableErrorsAreRejected(Map<String, Object> error) {
        assertThatThrownBy(() -> TestIds.make((String) error.get("arm"), (String) error.get("inputHash"),
                (Integer) error.get("rep"), (Integer) error.get("gen"), (String) error.get("path"),
                ((Number) error.get("line")).intValue(), new HashSet<>(), null, null))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void duplicateWithoutRegistryIsError() {
        Set<String> taken = new HashSet<>();
        TestIds.make("owl", "0123456789abcdef", 1, null, "a/owner.feature", 5, taken, null, null);
        assertThatThrownBy(() -> TestIds.make("owl", "0123456789abcdef", 1, null, "a/owner.feature", 5, taken, null, null))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("중복");
    }

    @Test
    void sameFeatureKeepsSlugAcrossCalls() {
        Map<String, String> slugs = new HashMap<>();
        String first = TestIds.make("owl", "0123456789abcdef", 1, null, "b/owner.feature", 5, new HashSet<>(), null, slugs);
        String again = TestIds.make("owl", "0123456789abcdef", 1, null, "b/owner.feature", 7, new HashSet<>(), null, slugs);
        assertThat(first.split("#")[0]).isEqualTo(again.split("#")[0]);
    }

    @Test
    void windowsSeparatorsAreNormalizedBeforeHashing() {
        assertThat(TestIds.featureSlug("features\\소유자.feature", "소유자"))
                .isEqualTo(TestIds.featureSlug("features/소유자.feature", "소유자"));
    }

    @Test
    void registryBuildsIdsFromGenerationFileAndResolvesUris(@TempDir Path dir) throws Exception {
        Path file = dir.resolve("testids.json");
        Files.writeString(file, "{\"arm\":\"jqa\",\"inputHash\":\"0123456789abcdef\",\"rep\":1,\"gen\":null,"
                + "\"features\":[{\"path\":\"features/b.feature\",\"name\":\"Owner\",\"pickles\":[{\"line\":4,\"name\":\"x\"}]},"
                + "{\"path\":\"features/a.feature\",\"name\":\"Owner\",\"pickles\":[{\"line\":2,\"name\":\"y\"},{\"line\":8,\"name\":\"z\"}]}]}");
        TestIds.Registry registry = TestIds.Registry.load(file);
        // 경로 순서로 slug를 받는다: a가 Owner, b가 Owner_2
        assertThat(registry.lookup("classpath:features/a.feature", 8).testId()).isEqualTo("E2E_jqa_01234567r1_Owner#L8");
        assertThat(registry.lookup("classpath:features/b.feature", 4).testId()).isEqualTo("E2E_jqa_01234567r1_Owner_2#L4");
        assertThat(registry.lookup("file:///work/gen/features/b.feature", 4).scenarioName()).isEqualTo("x");
        assertThat(registry.lookup("classpath:features/b.feature", 5)).isNull();
        assertThat(registry.size()).isEqualTo(3);
    }
}
