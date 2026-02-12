"""
LLM processing models for pet attribute extraction
"""
from enum import Enum
from typing import List, Optional, TypeVar, Generic
from pydantic import BaseModel, Field, ConfigDict

T = TypeVar("T")


class ExtractionStatus(str, Enum):
    PRESENT = "present"
    EXPLICIT_NONE = "explicit_none"
    NOT_MENTIONED = "not_mentioned"


class NullableField(Generic[T], BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    status: ExtractionStatus = Field(
        description=(
            "Indicates whether the information was explicitly present, "
            "explicitly stated as none / no restriction / not applicable, "
            "or not mentioned at all in the source text"
        )
    )
    value: Optional[T] = Field(
        default=None,
        description=(
            "Extracted value if status is 'present'. "
            "Must be null if status is 'explicit_none' or 'not_mentioned'."
        )
    )


class NullableBool(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[bool] = None


class NullableInt(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[int] = None


class NullableFloat(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[float] = None


class NullableStr(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[str] = None


class NullableStringList(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[List[str]] = None


# Predefined attribute values
PREDEFINED_ATTRIBUTE_VALUES = {
    "allowed_species": {
        "PET_TYPE_DOG": "Dog",
        "PET_TYPE_CAT": "Cat",
        "PET_TYPE_BIRD": "Bird",
        "PET_TYPE_FISH": "Fish",
        "PET_TYPE_SMALL": "Small Pets",
        "PET_TYPE_ALL": "All Pets",
        "PET_TYPE_SERVICE": "Service Animals",
        "PET_TYPE_DOMESTIC": "Domestic Animals",
    },
    "pet_amenities_list": {
        "AMENITY_PET_BEDS": "Pet Beds",
        "AMENITY_PET_BOWLS": "Pet Bowls",
        "AMENITY_PET_TREATS": "Pet Treats",
        "AMENITY_RELIEF_AREA": "Relief Area",
        "AMENITY_PET_MENU": "Pet Menu",
        "AMENITY_PET_TOYS": "Pet Toys",
        "AMENITY_KENNEL": "Kennel",
        "AMENITY_PET_SITTING": "Pet Sitting",
        "AMENITY_DOG_WALKING": "Dog Walking",
        "AMENITY_WASTE_BAGS": "Waste Bags",
        "AMENITY_WELCOME_KIT": "Welcome Kit",
        "AMENITY_FENCED_AREA": "Fenced Area",
        "AMENITY_DOG_WASH": "Dog Wash",
        "AMENITY_TRAILS": "Trails",
    },
    "breed_restrictions": {
        "BREED_AGGRESSIVE": "Aggressive Breeds",
        "BREED_LARGE": "Large Breeds",
        "BREED_CONTACT": "Contact for Restrictions",
        "BREED_AKITA": "Akita",
        "BREED_ALASKAN_MALAMUTE": "Alaskan Malamute",
        "BREED_AMERICAN_BULLDOG": "American Bulldog",
        "BREED_PIT_BULL": "Pit Bull",
        "BREED_STAFFORDSHIRE_TERRIER": "Staffordshire Terrier",
        "BREED_BELGIAN_MALINOIS": "Belgian Malinois",
        "BREED_BENGAL": "Bengal",
        "BREED_BOXER": "Boxer",
        "BREED_MASTIFF": "Mastiff",
        "BREED_BULL_TERRIER": "Bull Terrier",
        "BREED_BULLY": "Bully",
        "BREED_CANE_CORSO": "Cane Corso",
        "BREED_CHOW_CHOW": "Chow Chow",
        "BREED_DINGO": "Dingo",
        "BREED_DOBERMAN": "Doberman",
        "BREED_DOGO_ARGENTINO": "Dogo Argentino",
        "BREED_GERMAN_SHEPHERD": "German Shepherd",
        "BREED_GREAT_DANE": "Great Dane",
        "BREED_HUSKY": "Husky",
        "BREED_MIXED": "Mixed Breed",
        "BREED_PRESA_CANARIO": "Presa Canario",
        "BREED_ROTTWEILER": "Rottweiler",
        "BREED_SAVANNAH": "Savannah",
        "BREED_ST_BERNARD": "St. Bernard",
        "BREED_WOLF": "Wolf",
    },
}


class HotelPetRelatedInformation(BaseModel):
    is_pet_friendly: NullableBool = Field(
        description="Indicates if the hotel is pet-friendly. Example: True"
    )
    
    allowed_species: NullableStringList = Field(
        description=(
            "List of pet species allowed at the hotel. Use standardized codes. "
            "Examples: ['PET_TYPE_DOG'], ['PET_TYPE_CAT', 'PET_TYPE_DOG'], ['PET_TYPE_SERVICE']"
        ),
    )

    has_pet_deposit: NullableBool = Field(
        description="Indicates if a pet deposit is required",
    )

    pet_deposit_amount: NullableFloat = Field(
        description=(
            "Exact numeric amount required for pet deposit "
            "(extract this only if has_pet_deposit is True). "
            "Example: '$100 refundable deposit' -> 100"
        ),
    )

    is_deposit_refundable: NullableBool = Field(
        description=(
            "Indicates if the pet deposit is refundable "
            "(extract this only if has_pet_deposit is True)"
        ),
    )

    pet_fee_amount: NullableFloat = Field(
        description=(
            "Fee charged for pets staying at the hotel which is non-refundable in USD. "
            "(extract this only if is_pet_friendly is True)"
        ),
    )

    pet_fee_variations: NullableStringList = Field(
        description=(
            "Different pet fees based on size, weight, type or period. "
            "(extract this only if is_pet_friendly is True). "
            "Example: ['Small dogs: $50 per night', 'Large dogs: $75 per night', "
            "'1-4 nights: $75', '5+ nights: $125']"
        ),
    )

    pet_fee_currency: NullableStr = Field(
        description=(
            "Currency of the pet fee amount. "
            "(extract this only if is_pet_friendly is True). "
            "Example: 'usd', 'eur'"
        ),
    )

    pet_fee_interval: NullableStr = Field(
        description=(
            "Interval for the pet fee charged. "
            "(extract this only if is_pet_friendly is True) "
            "Example: 'per-night', 'per-stay', 'one-time'"
        ),
    )

    max_weight_lbs: NullableInt = Field(
        description=(
            "Maximum weight allowed per pet in lbs. "
            "(extract this only if is_pet_friendly is True) Example: 50"
        ),
    )

    max_pets_allowed: NullableInt = Field(
        description=(
            "Maximum number of pets allowed per room. "
            "(extract this only if is_pet_friendly is True) Example: 1"
        ),
    )

    breed_restrictions: NullableStringList = Field(
        description=(
            "List of breeds not allowed at the hotel. Use standardized codes. "
            "Examples: ['BREED_PIT_BULL'], "
            "['BREED_ROTTWEILER', 'BREED_BULLY'], ['BREED_LARGE']"
        ),
    )

    general_pet_rules: NullableStringList = Field(
        description=(
            "Summary of the hotel's pet policy except for the other specific rules. "
            "(extract this only if is_pet_friendly is True) "
            "Example: ['Pets must be leashed', "
            "'Cannot be left unattended in room', "
            "'Pets are not allowed in dining areas']"
        ),
    )

    has_pet_amenities: NullableBool = Field(
        description=(
            "Indicates if the hotel offers pet amenities such as pet beds, bowls, or a pet menu"
        ),
    )

    pet_amenities_list: NullableStringList = Field(
        description=(
            "List of pet amenities provided by the hotel "
            "(only if has_pet_amenities is True). "
            "Use standardized codes. "
            "Examples: ['AMENITY_PET_BEDS'], "
            "['AMENITY_PET_BOWLS', 'AMENITY_PET_TREATS'], "
            "['AMENITY_PET_MENU', 'AMENITY_DOG_WALKING']"
        ),
    )

    service_animals_allowed: NullableBool = Field(
        description="Whether service animals are allowed at this property",
    )

    emotional_support_animals_allowed: NullableBool = Field(
        description="Whether emotional support animals (ESA) are allowed at this property",
    )

    service_animal_policy: NullableStr = Field(
        description="Service animal policy details and requirements",
    )

    minimum_pet_age: NullableInt = Field(
        description="Minimum pet age requirement in months",
    )
    
    model_config = ConfigDict(arbitrary_types_allowed=True)


class HotelPetRelatedInformationConfidence(BaseModel):
    is_pet_friendly: float = Field(ge=0.0, le=1.0)
    allowed_species: float = Field(ge=0.0, le=1.0)
    has_pet_deposit: float = Field(ge=0.0, le=1.0)
    pet_deposit_amount: float = Field(ge=0.0, le=1.0)
    is_deposit_refundable: float = Field(ge=0.0, le=1.0)
    pet_fee_amount: float = Field(ge=0.0, le=1.0)
    pet_fee_currency: float = Field(ge=0.0, le=1.0)
    pet_fee_variations: float = Field(ge=0.0, le=1.0)
    pet_fee_interval: float = Field(ge=0.0, le=1.0)
    max_weight_lbs: float = Field(ge=0.0, le=1.0)
    max_pets_allowed: float = Field(ge=0.0, le=1.0)
    breed_restrictions: float = Field(ge=0.0, le=1.0)
    general_pet_rules: float = Field(ge=0.0, le=1.0)
    has_pet_amenities: float = Field(ge=0.0, le=1.0)
    pet_amenities_list: float = Field(ge=0.0, le=1.0)
    service_animals_allowed: float = Field(ge=0.0, le=1.0)
    emotional_support_animals_allowed: float = Field(ge=0.0, le=1.0)
    service_animal_policy: float = Field(ge=0.0, le=1.0)
    minimum_pet_age: float = Field(ge=0.0, le=1.0)


class HotelPetRelatedInformationWithConfidence(BaseModel):
    pet_information: HotelPetRelatedInformation
    confidence_scores: HotelPetRelatedInformationConfidence
    
    model_config = ConfigDict(arbitrary_types_allowed=True)