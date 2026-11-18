package td.minisut.api;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.hamcrest.Matchers.hasItem;

class TagApiBlackBoxIT extends ApiBlackBoxTestSupport {

    @Test
    @DisplayName("GET /api/tags returns the tags")
    void listTags() {
        authenticated().when().get("/api/tags")
            .then().statusCode(200).body("$", hasItem("fruit"));
    }
}
