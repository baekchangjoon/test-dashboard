package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import td.harness.Harness;

public class PetManagementSteps {
    private Response response;
    private Integer ownerId;
    private Integer typeId;
    private Object typeName;
    private Integer petId;
    private String petName;

    private void prepareOwnerAndType() {
        Response o = Harness.authed().contentType("application/json").body(ApiData.ownerBody()).post("/api/owners");
        assertThat(o.statusCode()).as(o.asString()).isIn(200, 201);
        ownerId = ApiData.extractId(o);
        assertThat(ownerId).isNotNull();
        Response types = Harness.authed().get("/api/pets/types");
        assertThat(types.statusCode()).as(types.asString()).isEqualTo(200);
        List<Integer> ids = ApiData.ids(types);
        assertThat(ids).isNotEmpty();
        typeId = ids.get(0);
        List<Object> names = ApiData.fieldValues(types, "name");
        typeName = names.isEmpty() ? null : names.get(0);
    }

    private Map<String, Object> petBody(String name) {
        Map<String, Object> type = new LinkedHashMap<>();
        type.put("id", typeId);
        if (typeName != null) {
            type.put("name", typeName);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("name", name);
        body.put("birthDate", "2020-05-01");
        body.put("ownerId", ownerId);
        body.put("typeId", typeId);
        body.put("type", type);
        return body;
    }

    private Response postPet(Map<String, Object> body) {
        return Harness.authed().contentType("application/json").body(body).post("/api/pets");
    }

    @When("the pet types are listed")
    public void listTypes() {
        response = Harness.authed().get("/api/pets/types");
    }

    @Then("the pet type listing is successful and not empty")
    public void typesOk() {
        assertThat(response.statusCode()).as(response.asString()).isEqualTo(200);
        assertThat(ApiData.ids(response)).isNotEmpty();
    }

    @Given("an owner and a pet type are available for a new pet")
    public void ownerAndType() {
        prepareOwnerAndType();
    }

    @When("a pet with a unique name is created for that owner")
    public void createPet() {
        petName = "Pet" + ApiData.letters(8);
        response = postPet(petBody(petName));
        petId = ApiData.extractId(response);
    }

    @Then("the pet is created with an id")
    public void petCreated() {
        assertThat(response.statusCode()).as(response.asString()).isIn(200, 201);
        assertThat(petId).isNotNull();
    }

    @Then("reading the pet by id returns the latest pet name")
    public void readPet() {
        Response r = Harness.authed().get("/api/pets/" + petId);
        assertThat(r.statusCode()).as(r.asString()).isEqualTo(200);
        assertThat(ApiData.str(r.jsonPath().get("name"))).isEqualTo(petName);
    }

    @Given("an existing pet created through the pet API")
    public void existingPet() {
        prepareOwnerAndType();
        createPet();
        petCreated();
    }

    @When("the pet is renamed to a unique name")
    public void renamePet() {
        petName = "Renamed" + ApiData.letters(8);
        Map<String, Object> body = petBody(petName);
        body.put("id", petId);
        response = Harness.authed().contentType("application/json").body(body).put("/api/pets/" + petId);
    }

    @Then("the pet update succeeds")
    public void petUpdated() {
        assertThat(response.statusCode()).as(response.asString()).isIn(200, 204);
    }

    @When("a pet with a blank name is created for that owner")
    public void blankPet() {
        response = postPet(petBody(""));
    }

    @Then("the pet request is rejected with a client error")
    public void petClientError() {
        assertThat(response.statusCode()).as(response.asString()).isBetween(400, 499);
    }

    @When("the pet with id {int} is requested")
    public void getUnknownPet(int id) {
        response = Harness.authed().get("/api/pets/" + id);
    }
}
