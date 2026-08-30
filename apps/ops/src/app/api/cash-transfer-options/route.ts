import { NextResponse } from 'next/server';
import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { fetchTransferOptions } from '@/lib/ops/transfers';
import { newCorrelationId } from '@/lib/logger';
export const dynamic='force-dynamic';
export async function GET(request: Request){
  if(!origineAcceptable(request)) return NextResponse.json({success:false,error:'Requête refusée.'},{status:403});
  const s=await readOpsSession(); if(!s)return NextResponse.json({success:false,error:'Session expirée.'},{status:401});
  try{return NextResponse.json({success:true,data:await fetchTransferOptions(s.odooSessionId,newCorrelationId())},{headers:{'Cache-Control':'no-store'}});}
  catch{return NextResponse.json({success:false,error:'Service momentanément indisponible.'},{status:503});}
}
