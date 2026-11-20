package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import td.harness.Harness;

public class PetManagementSteps {

    private String ownerId;
    private Object typeId;
    private String typeName;
    private String petName;
    private String petId;
    private Response response;

    @When("the pet types are requested")
    public void requestPetTypes() {
        response = Harness.authed().get("/api/pets/types");
    }

    @Then("the pet API response status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(expected);
    }

    @Then("the pet types list is not empty")
    public void typesNotEmpty() {
        List<Object> types = response.jsonPath().getList("$");
        assertThat(types).isNotEmpty();
    }

    @Given("an owner and a pet type are prepared for the pet test")
    public void prepareOwnerAndType() {
        Response created = ApiSupport.postJson("/api/owners", ApiSupport.ownerBody());
        assertThat(created.statusCode()).as("owner create response: %s", created.asString()).isIn(200, 201);
        ownerId = ApiSupport.extractId(created);
        assertThat(ownerId).isNotBlank();

        Response types = Harness.authed().get("/api/pets/types");
        assertThat(types.statusCode()).as(types.asString()).isEqualTo(200);
        List<Object> all = types.jsonPath().getList("$");
        assertThat(all).isNotEmpty();
        Object first = all.get(0);
        if (first instanceof Map) {
            Map<?, ?> type = (Map<?, ?>) first;
            typeId = type.get("id");
            Object name = type.get("name");
            typeName = name == null ? null : String.valueOf(name);
        } else {
            typeName = String.valueOf(first);
        }
    }

    private Object ownerIdValue() {
        try {
            return Long.valueOf(ownerId);
        } catch (NumberFormatException e) {
            return ownerId;
        }
    }

    private Map<String, Object> petBody(String name) {
        Map<String, Object> body = new HashMap<>();
        body.put("name", name);
        body.put("birthDate", "2020-01-15");
        body.put("ownerId", ownerIdValue());
        if (typeId != null) {
            body.put("typeId", typeId);
        }
        Map<String, Object> type = new HashMap<>();
        if (typeId != null) {
            type.put("id", typeId);
        }
        if (typeName != null) {
            type.put("name", typeName);
        }
        body.put("type", type);
        return body;
    }

    @When("a pet with a unique name is created for the prepared owner")
    public void createPet() {
        petName = "Rex" + ApiSupport.randomLetters(8);
        response = ApiSupport.postJson("/api/pets", petBody(petName));
    }

    @Then("the pet creation succeeds")
    public void creationSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isIn(200, 201);
        petId = ApiSupport.extractId(response);
        assertThat(petId).isNotBlank();
    }

    @When("the created pet is fetched")
    public void fetchPet() {
        response = Harness.authed().get("/api/pets/" + petId);
    }

    @Then("the fetched pet has the submitted name")
    public void fetchedPetHasName() {
        assertThat(response.jsonPath().getString("name")).isEqualTo(petName);
    }

    @When("the created pet is renamed")
    public void renamePet() {
        petName = "Max" + ApiSupport.randomLetters(8);
        response = ApiSupport.putJson("/api/pets/" + petId, petBody(petName));
    }

    @Then("the pet update succeeds")
    public void updateSucceeds() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(200, 299);
    }

    @When("a pet with a blank name is created for the prepared owner")
    public void createBlankPet() {
        response = ApiSupport.postJson("/api/pets", petBody(""));
    }

    @When("an unknown pet id is fetched")
    public void fetchUnknownPet() {
        response = Harness.authed().get("/api/pets/987654321");
    }

    @Then("the pet API response is a client error")
    public void clientError() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(400, 499);
    }
}
