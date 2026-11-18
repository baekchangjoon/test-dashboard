package td.minisut.api;

import java.util.Map;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.greaterThanOrEqualTo;
import static org.hamcrest.Matchers.hasItem;

class ItemApiBlackBoxIT extends ApiBlackBoxTestSupport {

    @Test
    @DisplayName("GET /api/items without a token is rejected")
    void listingItemsRequiresAuthentication() {
        given().when().get("/api/items").then().statusCode(401);
    }

    @Test
    @DisplayName("GET /api/items returns the seeded items")
    void listItems() {
        authenticated().when().get("/api/items")
            .then().statusCode(200)
            .body("size()", greaterThanOrEqualTo(2))
            .body("name", hasItem("apple"));
    }

    @Test
    @DisplayName("POST /api/items creates an item")
    void createItem() {
        authenticated().body(Map.of("name", "cherry")).when().post("/api/items")
            .then().statusCode(201).body("name", equalTo("cherry"));
    }
}
