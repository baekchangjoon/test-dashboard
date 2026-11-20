package glue;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

public class PetManagementSteps {

    private Response response;
    private String ownerId;
    private Integer typeId;
    private String petId;
    private String petName;

    @When("the pet types are requested")
    public void requestPetTypes() {
        response = Harness.authed().get("/api/pets/types");
    }

    @Then("the pet response status is {int}")
    public void petStatusIs(int expected) {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isEqualTo(expected);
    }

    @Then("the pet types response is a non-empty list")
    public void petTypesNonEmpty() {
        assertThat(ApiSupport.listItems(response)).isNotEmpty();
    }

    @Given("an owner and a pet type are available for the pet test")
    public void ownerAndTypeAvailable() {
        Response owner = Harness.authed().contentType("application/json").body(ApiSupport.newOwnerBody()).post("/api/owners");
        assertThat(owner.statusCode()).as("create owner: %s", owner.asString()).isBetween(200, 299);
        ownerId = ApiSupport.extractId(owner);
        assertThat(ownerId).isNotBlank();
        Response types = Harness.authed().get("/api/pets/types");
        assertThat(types.statusCode()).isEqualTo(200);
        List<Map<String, Object>> items = ApiSupport.listItems(types);
        assertThat(items).isNotEmpty();
        Object id = items.get(0).get("id");
        assertThat(id).isInstanceOf(Number.class);
        typeId = ((Number) id).intValue();
    }

    private Map<String, Object> petBody(String name) {
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("birthDate", "2020-05-17");
        body.put("ownerId", Integer.valueOf(ownerId));
        body.put("typeId", typeId);
        return body;
    }

    @When("a pet with a unique name is created for the pet test owner")
    public void createPet() {
        petName = "Rex" + ApiSupport.letters(8);
        response = Harness.authed().contentType("application/json").body(petBody(petName)).post("/api/pets");
        if (ApiSupport.isSuccess(response.statusCode())) {
            petId = ApiSupport.extractId(response);
        }
    }

    @Then("the pet creation succeeds")
    public void petCreationSucceeds() {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isBetween(200, 299);
        assertThat(petId).isNotBlank();
    }

    @Then("the created pet can be fetched with its submitted name")
    public void createdPetCanBeFetched() {
        Response fetched = Harness.authed().get("/api/pets/" + petId);
        assertThat(fetched.statusCode()).as("response body: %s", fetched.asString()).isEqualTo(200);
        assertThat(fetched.jsonPath().getString("name")).isEqualTo(petName);
    }

    @When("the created pet is renamed")
    public void renamePet() {
        assertThat(petId).as("pet id from creation").isNotBlank();
        petName = "Max" + ApiSupport.letters(8);
        Map<String, Object> body = petBody(petName);
        body.put("id", Integer.valueOf(petId));
        response = Harness.authed().contentType("application/json").body(body).put("/api/pets/" + petId);
    }

    @Then("the pet update succeeds")
    public void petUpdateSucceeds() {
        assertThat(response.statusCode()).as("response body: %s", response.asString()).isBetween(200, 299);
    }

    @Then("fetching the created pet shows the new name")
    public void fetchShowsNewName() {
        Response fetched = Harness.authed().get("/api/pets/" + petId);
        assertThat(fetched.statusCode()).isEqualTo(200);
        assertThat(fetched.jsonPath().getString("name")).isEqualTo(petName);
    }

    @When("an unknown pet id is fetched")
    public void fetchUnknownPet() {
        response = Harness.authed().get("/api/pets/" + ApiSupport.UNKNOWN_ID);
    }

    @When("a pet without a name is created for the pet test owner")
    public void createPetWithoutName() {
        Map<String, Object> body = petBody("unused");
        body.remove("name");
        response = Harness.authed().contentType("application/json").body(body).post("/api/pets");
    }
}
