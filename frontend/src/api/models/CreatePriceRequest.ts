import { PriceType } from './PriceType';

export interface CreatePriceRequest {
  productId: number;
  currency: string;
  amount: number;
  type: PriceType;
  validFrom: string;
  validTo?: string;
}
