Feature: Veterinarian directory API

  Scenario: The list of veterinarians can be retrieved
    When the client requests the veterinarian list
    Then the vet API responds with status 200
    And the veterinarian list is returned as a JSON body

  Scenario: Requesting an unknown veterinarian fails
    When the client requests a veterinarian with an unknown id
    Then the veterinarian lookup fails with a client error
