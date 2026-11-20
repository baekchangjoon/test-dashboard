package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import td.harness.Harness;

public class PetManagementSteps {

    private Integer ownerId;
    private Integer petId;
    private String petName;
    private String newPetName;
    private Response response;

    private Map<String, Object> petBody(String name) {
        Response types = Harness.authed().get("/api/pets/types");
        assertThat(types.statusCode()).isEqualTo(200);
        List<Object> typeIds = types.jsonPath().getList("id");
        List<Object> typeNames = types.jsonPath().getList("name");
        assertThat(typeIds).as("available pet types").isNotEmpty();
        Map<String, Object> type = new HashMap<>();
        type.put("id", typeIds.get(0));
        type.put("name", typeNames == null || typeNames.isEmpty() ? null : typeNames.get(0));
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("birthDate", "2020-05-17");
        body.put("ownerId", ownerId);
        body.put("typeId", typeIds.get(0));
        body.put("type", type);
        return body;
    }

    @When("the client lists the available pet types")
    public void listPetTypes() {
        response = Harness.authed().get("/api/pets/types");
    }

    @Given("a new owner who will own a pet")
    public void newOwnerForPet() {
        Map<String, Object> owner = ApiData.ownerBody(ApiData.uniqueName("Bob"), ApiData.uniqueName("Kim"),
                ApiData.uniqueName("City"), ApiData.phoneDigits());
        Response created = ApiData.postOwner(owner);
        assertThat(created.statusCode()).as(created.asString()).isBetween(200, 299);
        ownerId = ApiData.extractId(created);
        assertThat(ownerId).isNotNull();
    }

    @Given("a new pet with a unique name registered for that owner")
    public void newPetForOwner() {
        petName = ApiData.uniqueName("Rex");
        Response created = Harness.authed().contentType("application/json").body(petBody(petName)).post("/api/pets");
        assertThat(created.statusCode()).as(created.asString()).isBetween(200, 299);
        petId = ApiData.extractId(created);
        assertThat(petId).as("created pet id").isNotNull();
    }

    @When("the client fetches that pet by id")
    public void fetchThatPet() {
        response = Harness.authed().get("/api/pets/" + petId);
    }

    @When("the client renames that pet to a new unique name")
    public void renamePet() {
        newPetName = ApiData.uniqueName("Max");
        response = Harness.authed().contentType("application/json").body(petBody(newPetName)).put("/api/pets/" + petId);
    }

    @When("the client registers a pet without a name for that owner")
    public void registerPetWithoutName() {
        Map<String, Object> body = petBody("");
        response = Harness.authed().contentType("application/json").body(body).post("/api/pets");
    }

    @When("the client fetches a pet with an id that does not exist")
    public void fetchUnknownPet() {
        response = Harness.authed().get("/api/pets/987654321");
    }

    @Then("the pet response has status {int}")
    public void petResponseStatus(int status) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(status);
    }

    @Then("the pet type list is a JSON array whose entries carry a name")
    public void petTypesCarryName() {
        assertThat(response.asString().trim()).startsWith("[");
        List<Object> names = response.jsonPath().getList("name");
        assertThat(names).isNotNull();
        assertThat(names).doesNotContainNull();
    }

    @Then("the fetched pet has the registered name")
    public void fetchedPetHasName() {
        assertThat(response.jsonPath().getString("name")).isEqualTo(petName);
    }

    @Then("the pet update succeeds")
    public void petUpdateSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(200, 299);
    }

    @Then("fetching that pet shows the new name")
    public void fetchingPetShowsNewName() {
        Response read = Harness.authed().get("/api/pets/" + petId);
        assertThat(read.statusCode()).isEqualTo(200);
        assertThat(read.jsonPath().getString("name")).isEqualTo(newPetName);
    }
}
