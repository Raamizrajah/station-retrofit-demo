import { PriceType } from './PriceType';

export interface PriceEntryDto {
  id: number;
  productId: number;
  currency: string;
  amount: number;
  type: PriceType;
  validFrom: string;
  validTo?: string;
}
