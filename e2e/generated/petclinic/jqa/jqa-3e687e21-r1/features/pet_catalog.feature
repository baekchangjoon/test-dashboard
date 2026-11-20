Feature: Pet API

  Scenario: The pet type catalog can be retrieved
    When the client requests the pet type catalog
    Then the pet API responds with status 200
    And the pet type catalog is returned as a JSON body

  Scenario: Requesting an unknown pet fails
    When the client requests a pet with an unknown id
    Then the pet lookup fails with a client error
