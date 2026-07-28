export type GamePromoData = {
  gameTitle: string;
  shortTitle: string;
  locationName: string;
  countryName: string;
  clues: Array<{
    text: string;
    points: number;
  }>;
  callToAction: string;
  secondaryCallToAction: string;
  websiteUrl?: string;
};

export const defaultGamePromoData: GamePromoData = {
  gameTitle: "Guess the Location",
  shortTitle: "New Daily Game",
  locationName: "Kathmandu",
  countryName: "Nepal",
  clues: [
    {
      text: "This capital sits in a valley surrounded by Himalayan peaks.",
      points: 10,
    },
    {
      text: "It is the capital city of Nepal.",
      points: 7,
    },
    {
      text: "Its name begins with the letter K.",
      points: 5,
    },
    {
      text: "Kathmandu",
      points: 2,
    },
  ],
  callToAction: "Play Today's Location",
  secondaryCallToAction: "No peeking at clue 4.",
  websiteUrl: "/map",
};
