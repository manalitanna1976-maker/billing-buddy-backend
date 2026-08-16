import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";

import {
  Business,
  BusinessUpdateInput,
  getBusiness,
  updateBusiness,
  uploadLogo,
  uploadSignature,
} from "../api/business";
import AppShell from "../components/AppShell";
import { cardClass, cardTitleClass, inputClass, labelClass, primaryButtonClass } from "../styles";

const API_URL = import.meta.env.VITE_API_URL as string;

function UploadBox({
  label,
  imageUrl,
  onFile,
  isPending,
}: {
  label: string;
  imageUrl: string | null;
  onFile: (file: File) => void;
  isPending: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (file) onFile(file);
  }

  return (
    <div>
      <h3 className={cardTitleClass}>{label}</h3>
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={[
          "flex h-36 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-3 text-center transition-colors",
          dragOver ? "border-primary bg-primary/5" : "border-border bg-paper",
        ].join(" ")}
      >
        {imageUrl ? (
          <img src={`${API_URL}${imageUrl}`} alt={label} className="max-h-24 max-w-full object-contain" />
        ) : (
          <>
            <span className="text-sm font-medium text-ink-muted">
              {isPending ? "Uploading…" : "Click or drag a PNG/JPG here"}
            </span>
            <span className="mt-1 text-xs text-ink-muted">Recommended: transparent PNG</span>
          </>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
      {imageUrl && (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="mt-2 text-xs font-medium text-primary hover:underline"
        >
          Replace {label.toLowerCase()}
        </button>
      )}
    </div>
  );
}

export default function BusinessProfilePage() {
  const queryClient = useQueryClient();
  const { data: business, isLoading } = useQuery({ queryKey: ["business"], queryFn: getBusiness });
  const { register, handleSubmit, reset, formState } = useForm<BusinessUpdateInput>();

  useEffect(() => {
    if (business) reset(business);
  }, [business, reset]);

  const updateMutation = useMutation({
    mutationFn: updateBusiness,
    onSuccess: (data) => {
      queryClient.setQueryData<Business>(["business"], data);
      reset(data);
    },
  });

  const logoMutation = useMutation({
    mutationFn: uploadLogo,
    onSuccess: (data) => queryClient.setQueryData<Business>(["business"], data),
  });

  const signatureMutation = useMutation({
    mutationFn: uploadSignature,
    onSuccess: (data) => queryClient.setQueryData<Business>(["business"], data),
  });

  return (
    <AppShell title="Business Profile">
      {isLoading || !business ? (
        <p className="text-sm text-ink-muted">Loading…</p>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <form onSubmit={handleSubmit((values) => updateMutation.mutate(values))} className={cardClass}>
            <h2 className={cardTitleClass}>Company details</h2>
            <div className="space-y-3">
              <div>
                <label className={labelClass}>Business name</label>
                <input {...register("name", { required: true })} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}>GSTIN</label>
                <input {...register("gstin")} maxLength={15} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}>Address</label>
                <textarea {...register("address")} rows={2} className={inputClass} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelClass}>State</label>
                  <input {...register("state")} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}>Phone</label>
                  <input {...register("phone")} className={inputClass} />
                </div>
              </div>
              <div>
                <label className={labelClass}>Email</label>
                <input {...register("email")} type="email" className={inputClass} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelClass}>Invoice prefix</label>
                  <input {...register("invoice_prefix")} placeholder="INV-" className={inputClass} />
                </div>
                <div>
                  <label className={labelClass}>Invoice postfix</label>
                  <input {...register("invoice_postfix")} placeholder="/26-27" className={inputClass} />
                </div>
              </div>
              <button
                type="submit"
                disabled={updateMutation.isPending || !formState.isDirty}
                className={primaryButtonClass}
              >
                {updateMutation.isPending ? "Saving…" : "Save changes"}
              </button>
              {updateMutation.isSuccess && !formState.isDirty && (
                <span className="ml-3 text-sm text-success">Saved.</span>
              )}
            </div>
          </form>

          <div className="space-y-6">
            <div className={cardClass}>
              <UploadBox
                label="Logo"
                imageUrl={business.logo_url}
                onFile={(file) => logoMutation.mutate(file)}
                isPending={logoMutation.isPending}
              />
            </div>
            <div className={cardClass}>
              <UploadBox
                label="Signature"
                imageUrl={business.signature_url}
                onFile={(file) => signatureMutation.mutate(file)}
                isPending={signatureMutation.isPending}
              />
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
